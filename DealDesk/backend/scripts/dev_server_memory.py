"""The REAL API running entirely in memory, with a scripted writer. For trying the website end to end WITHOUT Supabase,
SQL files, a model or any key. Run from backend/:

    uv run python scripts/dev_server_memory.py          # serves http://127.0.0.1:8001 (port 8000 is left for the normal server)

Then start the website pointing at it:
    cd frontend && NEXT_PUBLIC_API_URL=http://127.0.0.1:8001 npm run dev -- -p 4000
and open http://localhost:4000. Everything is real except:
  - the deal is kept in memory (it is lost when you stop this program),
  - the buyer's wording comes from a scripted writer (the real checks still run on every message),
  - the market price is a fixed demo price.
The fake vendors, the Manager, the Best Offer Tracker, the take-control endpoints and the Limit Checker are the real code.
"""

import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000,http://localhost:4000,http://127.0.0.1:4000"

import uvicorn

from app.agents.assistant import AssistantDeps, InMemoryAssistantStore
from app.agents.manager import ManagerDeps
from app.agents.runtime import build_runtime, demo_delay
from app.api.assistant import get_assistant
from app.api.deals import get_agent_runtime, maybe_agent_runtime
from app.core.db import get_repo
from app.core.resume import _spawn
from app.schemas.records import (
    DealRecord,
    InMemoryDealStore,
    VendorRecord,
)
from app.simulator.scripted_llm import ScriptedLLM, fixed_research
from main import app

store = InMemoryDealStore()
BASE = datetime.now(UTC)


class MemoryRepo:
    """Gives the API the same two methods as the Supabase repo, on top of the in-memory store."""

    def create_deal(self, deal, vendors):
        deal_id = str(uuid.uuid4())
        rec = DealRecord(
            id=deal_id, item=deal["item"], max_price=float(deal["max_price"]), currency=deal["currency"],
            must_haves=list(deal["must_haves"]), address=deal["address"], phone=deal.get("phone"),
            variant=deal.get("variant", ""), alt_variants=list(deal.get("alt_variants", [])), addon_values=dict(deal.get("addon_values", {})),
        )  # fmt: skip
        for v in vendors:
            vid = str(uuid.uuid4())
            rec.vendors[vid] = VendorRecord(vid, v["name"], v["contact"], persona=v.get("persona"), played_by=v.get("played_by", "simulator"))
        store.add(rec)
        return deal_id

    def latest_deal_id(self):
        return list(store.deals)[-1] if store.deals else None

    def get_defaults(self, deal_id):
        d = store.deals.get(deal_id)
        if d is None:
            return None
        return {
            "address": d.address, "phone": d.phone, "addon_values": d.addon_values,
            "vendors": [{"name": v.name, "contact": v.contact, "channel": "email"} for v in d.vendors.values()],
        }  # fmt: skip

    def get_deal(self, deal_id):
        d = store.deals.get(deal_id)
        if d is None:
            return None
        stamp = lambda i: (BASE + timedelta(seconds=2 * i)).isoformat()
        return {
            "id": d.id, "item": d.item, "max_price": d.max_price, "currency": d.currency, "status": d.status, "accepted_vendor_id": d.accepted_vendor_id, "accepted_price": d.accepted_price,
            "variant": d.variant, "alt_variants": d.alt_variants, "addon_values": d.addon_values,
            "research": d.research.model_dump() if d.research else None,
            "vendors": [
                {
                    "id": v.vendor_id, "name": v.name, "channel": "email", "status": v.status, "offer_price": v.offer,
                    "recommendation": {"action": v.recommendation.action, "reason": v.recommendation.reason} if v.recommendation else None,
                    "stop_reason": v.stop_reason, "firm": v.firm, "played_by": v.played_by, "persona": v.persona,
                    "variant_prices": v.variant_prices, "addons": [{"key": a.key, "min_price": a.min_price} for a in v.addons],
                    "messages": [{"from": t.sender, "text": t.text, "simulated": t.simulated, "at": stamp(i)} for i, t in enumerate(v.conversation)],
                    "events": [{"agent": e.agent, "text": e.text, "sources": e.sources or None, "at": stamp(i)} for i, e in enumerate(v.events)],
                }
                for v in d.vendors.values()
            ],
        }  # fmt: skip


async def find_deal(vendor_id):
    return next((d.id for d in store.deals.values() if vendor_id in d.vendors), None)


runtime = build_runtime(
    store, lambda rt: ManagerDeps(llm=ScriptedLLM(), store=store, research=fixed_research, on_send=rt.on_send), find_deal, demo_delay  # type: ignore[arg-type]
)
repo = MemoryRepo()
app.dependency_overrides[get_repo] = lambda: repo
app.dependency_overrides[get_agent_runtime] = lambda: runtime
app.dependency_overrides[maybe_agent_runtime] = lambda: runtime
assistant_deps = AssistantDeps(llm=ScriptedLLM(), store=InMemoryAssistantStore(), repo=repo, start_deal=runtime.start_deal, spawn=_spawn)  # type: ignore[arg-type]
app.dependency_overrides[get_assistant] = lambda: assistant_deps

if __name__ == "__main__":
    print("DealDesk API in memory on http://127.0.0.1:8001 (scripted writer, fixed market price, fake vendors).")
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
