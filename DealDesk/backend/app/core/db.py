"""The only file that talks to Supabase.

The rest of the app depends on the small DealRepo interface, not on Supabase.
That means tests can swap in a fake repo, and we could change the database
later by rewriting only this file.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from supabase import Client, create_client

from app.agents.fact_rules import Turn
from app.core.config import get_settings
from app.negotiation.addons import AddonOffer
from app.negotiation.strategy import Recommendation
from app.negotiation.tactics import Tactics
from app.schemas.records import DealRecord, Event, VendorRecord
from app.schemas.research import ResearchResult


class DealRepo(Protocol):
    def create_deal(self, deal: dict[str, Any], vendors: list[dict[str, Any]]) -> str: ...

    def get_deal(self, deal_id: str) -> dict[str, Any] | None: ...

    def get_defaults(self, deal_id: str) -> dict[str, Any] | None: ...

    def latest_deal_id(self) -> str | None: ...


@lru_cache
def get_client() -> Client:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    # The service role key bypasses Row Level Security. It stays on the server only.
    return create_client(s.supabase_url, s.supabase_service_role_key)


class SupabaseDealRepo:
    def __init__(self, client: Client) -> None:
        self.db = client

    def create_deal(self, deal: dict[str, Any], vendors: list[dict[str, Any]]) -> str:
        deal_id = self.db.table("deals").insert(deal).execute().data[0]["id"]
        try:
            self.db.table("vendors").insert([{**v, "deal_id": deal_id} for v in vendors]).execute()
        except Exception:
            # PostgREST has no multi-table transaction, so undo the first insert by hand.
            self.db.table("deals").delete().eq("id", deal_id).execute()
            raise
        return deal_id

    def latest_deal_id(self) -> str | None:
        rows = self.db.table("deals").select("id,created_at").order("created_at").execute().data
        return rows[-1]["id"] if rows else None

    def get_defaults(self, deal_id: str) -> dict[str, Any] | None:
        """What the Assistant reuses for the next purchase: the vendor list, the delivery address, the phone and the extras you value.
        It is read on the server only. It never goes to a browser."""
        rows = self.db.table("deals").select("address,phone,addon_values").eq("id", deal_id).limit(1).execute().data
        if not rows:
            return None
        vendors = self.db.table("vendors").select("name,contact,channel").eq("deal_id", deal_id).order("created_at").execute().data
        return {"address": rows[0].get("address") or "", "phone": rows[0].get("phone"), "addon_values": rows[0].get("addon_values") or {}, "vendors": vendors}

    def get_deal(self, deal_id: str) -> dict[str, Any] | None:
        rows = (
            self.db.table("deals")
            .select("id,item,max_price,currency,status,research,accepted_vendor_id,accepted_price,variant,alt_variants,addon_values")
            .eq("id", deal_id)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            return None
        deal = rows[0]

        vendors = (
            self.db.table("vendors")
            .select("id,name,channel,status,offer_price,recommendation,stop_reason,firm,played_by,persona,variant_prices,addons")
            .eq("deal_id", deal_id)
            .order("created_at")
            .execute()
            .data
        )
        ids = [v["id"] for v in vendors]
        messages: list[dict] = []
        events: list[dict] = []
        if ids:
            messages = (
                self.db.table("messages")
                .select("vendor_id,sender,text,simulated,created_at")
                .in_("vendor_id", ids)
                .order("created_at")
                .execute()
                .data
            )
            events = (
                self.db.table("events")
                .select("vendor_id,agent,text,sources,created_at")
                .in_("vendor_id", ids)
                .order("created_at")
                .execute()
                .data
            )

        for v in vendors:
            v["messages"] = [
                {"from": m["sender"], "text": m["text"], "simulated": bool(m.get("simulated")), "at": m["created_at"]}
                for m in messages
                if m["vendor_id"] == v["id"]
            ]
            v["events"] = [
                {"agent": e["agent"], "text": e["text"], "sources": e["sources"], "at": e["created_at"]}
                for e in events
                if e["vendor_id"] == v["id"]
            ]
        deal["vendors"] = vendors
        return deal


def get_repo() -> DealRepo:
    """FastAPI calls this to get the repo. Tests replace it with a fake."""
    return SupabaseDealRepo(get_client())


# ---------------------------------------------------------------- the agent's store (what lets a restart resume)

# The columns of `vendors` the agent writes. Anything else (name, contact, persona, lease) is not touched by the agent.
_STATUS_FROM_DB = {"sent": "negotiating", "replied": "negotiating"}


def _vendor_fields(v: VendorRecord) -> dict[str, Any]:
    return {
        "status": v.status,
        "offer_price": v.offer,
        "offers_so_far": list(v.offers_so_far),
        "last_counter": v.last_counter,
        "rounds": v.rounds,
        "stall_count": v.stall_count,
        "firm": v.firm,
        "firm_pushes": v.firm_pushes,
        "last_leverage": v.last_leverage,
        "stop_reason": v.stop_reason,
        "variant_prices": dict(v.variant_prices),
        "addons": [{"key": a.key, "min_price": a.min_price} for a in v.addons],
        "played_by": v.played_by,
        "recommendation": {"action": v.recommendation.action, "reason": v.recommendation.reason} if v.recommendation else None,
    }


def _deal_fields(d: DealRecord) -> dict[str, Any]:
    return {
        "research": d.research.model_dump() if d.research is not None else None,
        "tactics": d.tactics.model_dump(),
        "variant": d.variant,
        "alt_variants": list(d.alt_variants),
        "addon_values": dict(d.addon_values),
        "status": d.status,
        "accepted_vendor_id": d.accepted_vendor_id,
        "accepted_price": d.accepted_price,
        "max_rounds": d.max_rounds,
        "ceiling_ratio": d.ceiling_ratio,
    }


class SupabaseDealStore:
    """Keeps the Manager's DealRecord in Supabase.

    - `get` loads the deal once per server run and keeps it in memory (a write-through cache), so the many steps of
      one turn do not each hit the database. After a restart the deal is loaded from the database again.
    - `save` writes ONLY what changed since the last save: changed vendor rows, new messages, new events, and the deal's
      research and tactics. Turns for different vendors therefore never overwrite each other.
    - The comparison happens in the event loop (fast, no await), and only the database calls run in a thread.
    - One server instance works on a vendor at a time (the lease in core/resume.py). A second instance would need locks.
    """

    def __init__(self, client: Client) -> None:
        self.db = client
        self._cache: dict[str, DealRecord] = {}
        self._snap: dict[str, dict[str, Any]] = {}
        self._written = 0  # a counter that keeps message timestamps in order

    # ------------------------------------------------------------ load

    async def get(self, deal_id: str) -> DealRecord:
        if deal_id not in self._cache:
            record = await asyncio.to_thread(self._load, deal_id)
            self._cache[deal_id] = record
            self._snap[deal_id] = self._snapshot(record)
        return self._cache[deal_id]

    def _load(self, deal_id: str) -> DealRecord:
        s = get_settings()
        rows = self.db.table("deals").select("*").eq("id", deal_id).limit(1).execute().data
        if not rows:
            raise KeyError(f"No deal {deal_id}")
        d = rows[0]
        deal = DealRecord(
            id=d["id"],
            item=d["item"],
            max_price=float(d["max_price"]),
            currency=d["currency"],
            must_haves=list(d.get("must_haves") or []),
            address=d.get("address") or "",
            phone=d.get("phone"),
            research=ResearchResult(**d["research"]) if d.get("research") else None,
            tactics=Tactics(**d["tactics"]) if d.get("tactics") else Tactics(),
            variant=d.get("variant") or "",
            alt_variants=list(d.get("alt_variants") or []),
            addon_values={k: float(x) for k, x in (d.get("addon_values") or {}).items()},
            status="negotiating" if d.get("status") in (None, "created") else d["status"],
            accepted_vendor_id=d.get("accepted_vendor_id"),
            accepted_price=_num(d.get("accepted_price")),
            max_rounds=d.get("max_rounds") or s.max_rounds,
            ceiling_ratio=float(d["ceiling_ratio"]) if d.get("ceiling_ratio") else s.ceiling_ratio,
        )
        vendors = self.db.table("vendors").select("*").eq("deal_id", deal_id).order("created_at").execute().data
        ids = [v["id"] for v in vendors]
        messages = self.db.table("messages").select("*").in_("vendor_id", ids).order("created_at").execute().data if ids else []
        events = self.db.table("events").select("*").in_("vendor_id", ids).order("created_at").execute().data if ids else []
        for v in vendors:
            rec = v.get("recommendation")
            deal.vendors[v["id"]] = VendorRecord(
                vendor_id=v["id"],
                name=v["name"],
                contact=v["contact"],
                status=_STATUS_FROM_DB.get(v["status"], v["status"]),
                stop_reason=v.get("stop_reason"),
                offer=_num(v.get("offer_price")),
                offers_so_far=[float(x) for x in (v.get("offers_so_far") or [])],
                last_counter=_num(v.get("last_counter")),
                rounds=v.get("rounds") or 0,
                stall_count=v.get("stall_count") or 0,
                firm=bool(v.get("firm")),
                firm_pushes=v.get("firm_pushes") or 0,
                last_leverage=_num(v.get("last_leverage")),
                recommendation=Recommendation(rec["action"], rec["reason"]) if rec else None,
                conversation=[
                    Turn(sender=m["sender"], text=m["text"], simulated=bool(m.get("simulated"))) for m in messages if m["vendor_id"] == v["id"]
                ],
                events=[Event(e["agent"], e["text"], e.get("sources") or []) for e in events if e["vendor_id"] == v["id"]],
                persona=v.get("persona"),
                variant_prices={k: float(x) for k, x in (v.get("variant_prices") or {}).items()},
                addons=[AddonOffer(a["key"], _num(a.get("min_price"))) for a in (v.get("addons") or [])],
                played_by=v.get("played_by") or "simulator",
            )
        return deal

    # ------------------------------------------------------------ save

    @staticmethod
    def _snapshot(deal: DealRecord) -> dict[str, Any]:
        return {
            "deal": _deal_fields(deal),
            "vendors": {vid: (_vendor_fields(v), len(v.conversation), len(v.events)) for vid, v in deal.vendors.items()},
        }

    async def save(self, deal: DealRecord) -> None:
        old = self._snap.get(deal.id)
        new = self._snapshot(deal)
        ops = self._diff(deal, old, new)
        self._snap[deal.id] = new  # the comparison is done, so mark it as saved before the first await
        self._cache[deal.id] = deal
        if not ops:
            return
        try:
            await asyncio.to_thread(self._run, ops)
        except Exception:
            self._snap[deal.id] = old if old is not None else new  # the next save will try the same changes again
            raise

    def _diff(self, deal: DealRecord, old: dict[str, Any] | None, new: dict[str, Any]) -> list[tuple]:
        ops: list[tuple] = []
        if old is None or old["deal"] != new["deal"]:
            ops.append(("update", "deals", deal.id, new["deal"]))
        now = datetime.now(UTC)
        for vid, v in deal.vendors.items():
            fields, n_msg, n_evt = new["vendors"][vid]
            before = old["vendors"].get(vid) if old else None
            if before is None or before[0] != fields:
                ops.append(("update", "vendors", vid, {**fields, "updated_at": now.isoformat()}))
            seen_msg, seen_evt = (before[1], before[2]) if before else (0, 0)
            if n_msg > seen_msg:
                rows = []
                for t in v.conversation[seen_msg:]:
                    self._written += 1
                    rows.append({"vendor_id": vid, "sender": t.sender, "text": t.text, "simulated": t.simulated, "created_at": (now + timedelta(microseconds=self._written)).isoformat()})
                ops.append(("insert", "messages", rows))
            if n_evt > seen_evt:
                rows = []
                for e in v.events[seen_evt:]:
                    self._written += 1
                    rows.append({"vendor_id": vid, "agent": e.agent, "text": e.text, "sources": e.sources or None, "created_at": (now + timedelta(microseconds=self._written)).isoformat()})
                ops.append(("insert", "events", rows))
        return ops

    def _run(self, ops: list[tuple]) -> None:
        for op in ops:
            if op[0] == "update":
                _, table, row_id, payload = op
                self.db.table(table).update(payload).eq("id", row_id).execute()
            else:
                _, table, rows = op
                self.db.table(table).insert(rows).execute()


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


class SupabaseAssistantStore:
    """The Assistant's chat and what it is waiting for. One thread ('main') that never closes."""

    THREAD = "main"
    KEEP = 200  # the last messages sent to the website

    def __init__(self, client: Client) -> None:
        self.db = client

    async def load(self):
        return await asyncio.to_thread(self._load)

    def _load(self):
        from app.agents.assistant import AssistantState, ChatMessage

        t = self.db.table("assistant_threads").select("state").eq("id", self.THREAD).limit(1).execute().data
        state = AssistantState(**t[0]["state"]) if t and t[0].get("state") else AssistantState()
        rows = self.db.table("assistant_messages").select("sender,text,deal_id,created_at").eq("thread_id", self.THREAD).order("created_at").execute().data
        msgs = [ChatMessage(sender=r["sender"], text=r["text"], deal_id=r.get("deal_id"), at=r["created_at"]) for r in rows[-self.KEEP :]]
        return state, msgs

    async def add(self, sender: str, text: str, deal_id: str | None = None) -> None:
        await asyncio.to_thread(
            lambda: self.db.table("assistant_messages").insert({"thread_id": self.THREAD, "sender": sender, "text": text, "deal_id": deal_id}).execute()
        )

    async def save_state(self, state) -> None:
        def run() -> None:
            self.db.table("assistant_threads").upsert({"id": self.THREAD, "state": state.model_dump(), "updated_at": datetime.now(UTC).isoformat()}).execute()

        await asyncio.to_thread(run)


# ---------------------------------------------------------------- stored evaluation runs (the Scorecard reads only these)


def to_scorecard_run(result: dict) -> dict:
    """One stored run as the Scorecard shows it: the contract fields (CLAUDE.md 8.1) plus the rubric and the attack suite."""
    keys = ("mode", "model", "judge_model", "judge_note", "n_deals", "closed_pct", "limit_breaks", "private_shared", "invented_facts",
            "tricks_blocked_pct", "avg_savings_pct", "research_accuracy_pct", "ran_at")  # fmt: skip
    out = {k: result.get(k) for k in keys}
    out["judge_model"] = out["judge_model"] or "none"
    out["judge_note"] = out["judge_note"] or ""
    out.update({k: result.get(k) for k in ("rubric", "detail", "attack_suite", "run_id", "seed", "n_errors")})
    return out


def latest_per_mode(runs: list[dict]) -> list[dict]:
    """Newest first, one run per mode."""
    seen: set[str] = set()
    out = []
    for r in sorted(runs, key=lambda r: r.get("ran_at") or "", reverse=True):
        if r.get("mode") not in seen:
            seen.add(r["mode"])
            out.append(to_scorecard_run(r))
    return out


class SupabaseEvalStore:
    def __init__(self, client: Client) -> None:
        self.db = client

    def save(self, result: dict) -> None:
        self.db.table("eval_runs").insert(
            {
                "model": result["model"], "judge_model": result.get("judge_model"), "judge_note": result.get("judge_note"),
                "mode": result["mode"], "n_deals": result["n_deals"], "metrics": result,
            }
        ).execute()  # fmt: skip

    def runs(self) -> list[dict]:
        rows = self.db.table("eval_runs").select("metrics,created_at").order("created_at").execute().data
        return [{**(r["metrics"] or {}), "ran_at": (r["metrics"] or {}).get("ran_at") or r["created_at"]} for r in rows]


class FileEvalStore:
    """The same runs, read from app/evals/results/*.json. Used when no database is configured."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def runs(self) -> list[dict]:
        out = []
        for p in sorted(self.folder.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                continue
        return out


def get_eval_store():
    """FastAPI calls this. Tests replace it."""
    s = get_settings()
    if s.supabase_url and s.supabase_service_role_key:
        return SupabaseEvalStore(get_client())
    return FileEvalStore(Path(__file__).resolve().parent.parent / "evals" / "results")
