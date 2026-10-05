"""The evaluation runner. Run from backend/:

    uv run python -m app.evals.runner --deals 10 --mode both --seed 7 --store-db

It runs the scenarios through the product exactly as it runs (`safety_on`) and through the unprotected baseline (`safety_off`), runs the
attack suite, computes the metrics and the rubric from what really happened, and stores the result (JSON in app/evals/results/ and the
`eval_runs` table). The numbers on the Scorecard come only from these stored runs.
"""

import argparse
import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.agents.manager import ManagerDeps
from app.agents.runtime import build_runtime
from app.core import resume
from app.core.config import get_settings
from app.core.llm import LLM, usage_log
from app.evals import attacks, baseline, judge, metrics, rubric
from app.evals.owner import Candidate, choose
from app.evals.scenarios import ADDRESS, PHONE, Scenario, build_scenarios
from app.evals.transcript import DealTranscript, VendorTranscript
from app.schemas.records import DealRecord, InMemoryDealStore, VendorRecord
from app.schemas.research import ResearchResult, Source
from app.simulator.vendor_sim import VendorSim

RESULTS = Path(__file__).resolve().parent / "results"
JUDGE_NOTE = "No LLM judge was used. Invented facts are counted by rules only (fact_rules.py), so subtle invented claims may be missed."
JUDGE_NOTE_ON = (
    "An LLM judge graded the tone of every vendor chat (natural, relevant, patient, varied). It never decides a price, a limit or a pass or fail. "
    "It is the same small model family as the agent, so it is lenient: a rough signal only. Invented facts are still counted by rules."
)


def _research_for(scn: Scenario):
    async def fn(deal: DealRecord) -> ResearchResult:
        p = scn.product
        return ResearchResult(
            currency=p.currency, low=p.low, median=p.median, high=p.high, n_sources=3, regions=["US", "UK"], confidence="medium", available=True,
            sources=[Source(title="Fixture market range", url="https://fixture.example.com", price=p.median, region="US")],
        )  # fmt: skip

    return fn


def _usage(deal_id: str, t: DealTranscript) -> None:
    recs = [r for r in usage_log.records if r.deal_id == deal_id]
    t.calls, t.prompt_tokens, t.completion_tokens = len(recs), sum(r.prompt_tokens for r in recs), sum(r.completion_tokens for r in recs)


async def _settle() -> None:
    while resume._tasks:
        await resume.wait_for_tasks()


# ---------------------------------------------------------------- safety_on: the product as it runs


async def run_protected(scn: Scenario, llm: LLM) -> DealTranscript:
    from app.agents import closer

    deal_id = f"eval-{scn.id}-{uuid.uuid4().hex[:6]}"
    t = DealTranscript(scn, "safety_on", [VendorTranscript(f"Vendor {chr(65 + j)}", p) for j, p in enumerate(scn.vendor_personas)])
    store = InMemoryDealStore()
    deal = DealRecord(
        id=deal_id, item=scn.product.item, must_haves=list(scn.product.must_haves), currency=scn.product.currency, max_price=scn.max_price,
        address=ADDRESS, phone=PHONE, max_rounds=scn.max_rounds,
    )  # fmt: skip
    for j, p in enumerate(scn.vendor_personas):
        deal.vendors[f"v{j}"] = VendorRecord(f"v{j}", t.vendors[j].name, f"vendor{j}@shop.example.com", persona=p)
    store.add(deal)
    started = time.monotonic()
    rt = build_runtime(store, lambda r: ManagerDeps(llm=llm, store=store, research=_research_for(scn), on_send=r.on_send), None, lambda: 0.0)
    await rt.start_deal(deal_id)
    await _settle()

    candidates = [Candidate(j, v.offer, v.recommendation.action if v.recommendation else None) for j, v in enumerate(deal.vendors.values()) if v.offer is not None]
    pick = choose(candidates, scn.max_price)
    try:
        if pick is not None:
            await closer.accept(store, deal_id, f"v{pick}")
            t.accepted_vendor, t.accepted_by = pick, "owner"
            t.accepted_price = deal.vendors[f"v{pick}"].offer
        else:
            await closer.finish(store, deal_id, "reject_all")
    except closer.DecisionError as e:
        t.error = f"owner decision failed: {e.message}"

    for j, v in enumerate(deal.vendors.values()):
        vt = t.vendors[j]
        vt.messages = [("vendor" if x.sender == "vendor" else "agent", x.text) for x in v.conversation]
        vt.offers_read = list(v.offers_so_far)
        vt.blocked = v.status == "blocked" or v.stop_reason == "injection"
        vt.events = [f"{e.agent}: {e.text}" for e in v.events]
        vt.rounds, vt.firm_pushes = v.rounds, v.firm_pushes
        if pick == j:
            vt.closing_index = len(vt.messages) - 1
    if pick is not None:
        first = metrics.prices_in(next((x for s, x in t.vendors[pick].messages if s == "vendor"), ""))
        t.opening_price = first[0] if first else None
    t.seconds = time.monotonic() - started
    _usage(deal_id, t)
    return t


# ---------------------------------------------------------------- safety_off: the unprotected baseline


async def run_baseline(scn: Scenario, llm: LLM) -> DealTranscript:
    deal_id = f"eval-off-{scn.id}-{uuid.uuid4().hex[:6]}"
    t = DealTranscript(scn, "safety_off", [VendorTranscript(f"Vendor {chr(65 + j)}", p) for j, p in enumerate(scn.vendor_personas)])
    started = time.monotonic()
    p = scn.product
    last_price: dict[int, float] = {}
    first_price: dict[int, float] = {}

    async def one(j: int) -> None:
        vt = t.vendors[j]
        sim = VendorSim(vt.persona, p.median, p.item, p.currency, seed=scn.seed + j)
        turn = await sim.opening()
        vt.messages.append(("vendor", turn.text))
        first_price[j] = last_price[j] = turn.price or 0.0
        for _ in range(scn.max_rounds + 2):
            a = await baseline.decide(llm, p.item, scn.max_price, ADDRESS, PHONE, vt.messages, deal_id)
            if a.message.strip():
                vt.messages.append(("agent", a.message.strip()))
            if a.action == "accept":
                vt.agent_accepted_at = last_price[j]
                return
            if a.action == "reject":
                return
            price = a.price if a.price else (metrics.prices_in(a.message) or [None])[-1]
            if not price:
                return
            vt.rounds += 1
            turn = await sim.reply(price)
            vt.messages.append(("vendor", turn.text))
            last_price[j] = turn.price or last_price[j]

    await asyncio.gather(*(one(j) for j in range(len(t.vendors))))
    alone = [(vt.agent_accepted_at, j) for j, vt in enumerate(t.vendors) if vt.agent_accepted_at is not None]
    if alone:  # the agent acted on its own: no owner, no limit
        price, j = min(alone)
        t.accepted_vendor, t.accepted_price, t.accepted_by = j, price, "agent"
    else:
        pick = choose([Candidate(j, last_price[j], None) for j in last_price], scn.max_price, require_advice=False)
        if pick is not None:
            t.accepted_vendor, t.accepted_price, t.accepted_by = pick, last_price[pick], "owner"
    if t.accepted_vendor is not None:
        t.opening_price = first_price.get(t.accepted_vendor)
    t.seconds = time.monotonic() - started
    _usage(deal_id, t)
    return t


# ---------------------------------------------------------------- a whole run


async def run_mode(mode: str, scenarios: list[Scenario], llm: LLM, timeout: float, log=print) -> list[DealTranscript]:
    fn = run_protected if mode == "safety_on" else run_baseline
    out = []
    for scn in scenarios:
        t0 = time.monotonic()
        try:
            t = await asyncio.wait_for(fn(scn, llm), timeout)
        except TimeoutError:
            t = DealTranscript(scn, mode, error=f"timed out after {timeout:.0f}s")
        except Exception as e:  # noqa: BLE001  (one broken deal must not stop the whole run; it is recorded as an error)
            t = DealTranscript(scn, mode, error=f"{type(e).__name__}: {e}")
        out.append(t)
        log(f"  [{mode}] deal {scn.id + 1}/{len(scenarios)} {scn.product.item} vs {scn.persona}: closed={t.accepted_price} by={t.accepted_by} "
            f"calls={t.calls} tokens={t.prompt_tokens + t.completion_tokens} {time.monotonic() - t0:.0f}s {t.error}")  # fmt: skip
    return out


def summarize(mode: str, deals: list[DealTranscript], suite: dict | None, llm_model: str, seed: int, judged: dict | None = None) -> dict:
    good = [d for d in deals if not d.error]
    m = metrics.aggregate(good) if good else metrics.aggregate([])
    r = rubric.score(m, vendors_per_deal=3) if good else None
    return {
        "mode": mode, "model": llm_model, "judge_model": judged["model"] if judged else "none", "judge_note": JUDGE_NOTE_ON if judged else JUDGE_NOTE, "n_deals": len(good), "n_errors": len(deals) - len(good), "seed": seed,
        "closed_pct": round(m["closed_pct"], 2), "limit_breaks": m["limit_breaks"], "private_shared": m["private_shared"], "invented_facts": m["invented_facts"],
        "tricks_blocked_pct": round(suite["handled_pct"], 2) if suite else None,
        "avg_savings_pct": round(m["avg_savings_pct"], 2), "research_accuracy_pct": None,
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "detail": {
            "agent_acted_alone": m["agent_acted_alone"], "calls_per_deal": round(m["calls_per_deal"], 1), "tokens_per_deal": round(m["tokens_per_deal"]),
            "seconds_per_deal": round(m["seconds_per_deal"]), "message_quality": round(m["_quality"], 4), "reading_accuracy": m["_reading"],
            **({"judge": judged} if judged else {}),
            "research_note": "Not measured in this run: the market range is a fixed fixture, so there is no research to grade.",
        },
        "rubric": r, "attack_suite": suite,
        "deals": [{"id": d.scenario.id, "item": d.scenario.product.item, "persona": d.scenario.persona, "max_price": d.scenario.max_price, "closed_at": d.accepted_price,
                   "accepted_by": d.accepted_by, "calls": d.calls, "tokens": d.prompt_tokens + d.completion_tokens, "seconds": round(d.seconds), "error": d.error} for d in deals],
    }  # fmt: skip


def save(result: dict, transcripts: list[DealTranscript], store_db: bool) -> Path:
    RESULTS.mkdir(exist_ok=True)
    run_id = f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{result['mode']}"
    result = {**result, "run_id": run_id}
    path = RESULTS / f"{run_id}.json"
    chats = [{"deal": d.scenario.id, "vendors": [{"persona": v.persona, "messages": v.messages, "events": v.events} for v in d.vendors]} for d in transcripts]
    path.write_text(json.dumps({**result, "transcripts": chats}, indent=2))
    if store_db:
        from app.core.db import SupabaseEvalStore, get_client

        SupabaseEvalStore(get_client()).save(result)
    return path


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deals", type=int, default=10)
    ap.add_argument("--mode", choices=["safety_on", "safety_off", "both"], default="both")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--timeout", type=float, default=2400, help="seconds allowed per deal")
    ap.add_argument("--judge", action="store_true", help="grade the tone of every vendor chat with the LLM judge")
    ap.add_argument("--no-suite", action="store_true", help="skip the attack suite")
    ap.add_argument("--store-db", action="store_true", help="also write the result to the eval_runs table in Supabase")
    args = ap.parse_args()

    s = get_settings()
    llm = LLM(s)  # no database budget: a local evaluation
    scenarios = build_scenarios(args.deals, args.seed)
    print(f"Evaluation: {args.deals} deals, mode {args.mode}, seed {args.seed}, model {s.llm_model_main} ({s.llm_provider})")
    for mode in (["safety_off", "safety_on"] if args.mode == "both" else [args.mode]):
        t0 = time.monotonic()
        suite = None
        if not args.no_suite:
            print(f"== {mode}: attack suite ({len(attacks.SUITE)} attacks)")
            res = await (attacks.run_protected(llm) if mode == "safety_on" else attacks.run_baseline(llm))
            suite = attacks.summarize(res)
            print(f"   handled {suite['handled_pct']:.1f}%  (obvious {suite['by_level']['obvious']}, sneaky {suite['by_level']['sneaky']})")
        print(f"== {mode}: {len(scenarios)} deals")
        deals = await run_mode(mode, scenarios, llm, args.timeout)
        judged = await judge.judge_deals(deals, llm, s.llm_model_fast) if args.judge else None
        result = summarize(mode, deals, suite, s.llm_model_main, args.seed, judged)
        path = save(result, deals, args.store_db)
        r = result["rubric"]
        print(f"   {mode}: closed {result['closed_pct']}%  limit_breaks {result['limit_breaks']}  private_shared {result['private_shared']}  "
              f"invented {result['invented_facts']}  tricks_handled {result['tricks_blocked_pct']}  savings {result['avg_savings_pct']}%")  # fmt: skip
        if judged:
            print(f"   judge ({judged['model']}): {judged['n_graded']} chats graded, mean {judged['mean']}, {judged['criteria']}")
        if r:
            print(f"   rubric {r['overall']:.3f} ({'PASS' if r['passed'] else 'FAIL'}) {r['criteria']}  hard failures: {r['hard_failures']}")
        print(f"   saved {path.name} in {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
