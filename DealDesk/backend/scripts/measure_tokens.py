"""Measures the REAL token usage of the agent pipeline with the real model (Ollama locally, Groq when APP_ENV=production).

Run from backend/ (it takes 10 to 30 minutes on a laptop model, so start it and let it work):
    uv run python scripts/measure_tokens.py --label before
    uv run python scripts/measure_tokens.py --label after --with-research
It writes data/llm_usage_<label>.jsonl (one line per model call) and data/token_run_<label>.json (totals per scenario).
Then:  uv run python scripts/token_report.py   rebuilds the tables in docs/TOKEN_USAGE.md from those files.

Scenarios (the same every time, so before and after can be compared):
  A. a deal with 3 fake vendors (friendly, pushy, stubborn), 3 rounds, a fixed market price of $700
  B. the assistant chat: a purchase request and an unusual message (the two that need the model)
  C. (--with-research) one real market-price research for "Dell XPS 15" (about 5 Tavily credits)
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from app.agents.assistant import AssistantDeps, InMemoryAssistantStore, handle
from app.agents.manager import ManagerDeps
from app.agents.runtime import build_runtime
from app.core import resume
from app.core.config import get_settings
from app.core.llm import LLM, usage_log
from app.schemas.records import DealRecord, InMemoryDealStore, VendorRecord
from app.simulator.scripted_llm import fixed_research

DATA = Path(__file__).resolve().parent.parent / "data"


def snapshot() -> dict:
    s = usage_log.summary()
    return {"calls": s["total"]["calls"], "prompt": s["total"]["prompt_tokens"], "completion": s["total"]["completion_tokens"], "total": s["total"]["total_tokens"], "by_agent": s["by_agent"]}


async def settle() -> None:
    while resume._tasks:
        await resume.wait_for_tasks()


async def scenario_deal(llm: LLM) -> None:
    store = InMemoryDealStore()
    deal = DealRecord(id="measure-deal", item="Dell XPS 15", must_haves=["16GB RAM"], max_price=800.0, address="12 Example Street, Karachi", max_rounds=3)
    for vid, name, persona in (("v1", "Alpha", "friendly"), ("v2", "Beta", "pushy"), ("v3", "Gamma", "stubborn")):
        deal.vendors[vid] = VendorRecord(vid, name, f"{name.lower()}@shop.example.com", persona=persona)
    store.add(deal)
    rt = build_runtime(store, lambda r: ManagerDeps(llm=llm, store=store, research=fixed_research, on_send=r.on_send), None, lambda: 0.0)
    await rt.start_deal("measure-deal")
    await settle()
    for v in deal.vendors.values():
        print(f"   {v.name}: status={v.status} offer={v.offer} rounds={v.rounds} messages={len(v.conversation)}")


class StubRepo:
    def get_defaults(self, deal_id):
        return {"address": "12 Example Street", "phone": None, "addon_values": {}, "vendors": [{"name": "Alpha", "contact": "a@x.com", "channel": "email"}]}

    def latest_deal_id(self):
        return "d1"

    def get_deal(self, deal_id):
        return None

    def create_deal(self, deal, vendors):
        return "d2"


async def scenario_assistant(llm: LLM) -> None:
    deps = AssistantDeps(llm=llm, store=InMemoryAssistantStore(), repo=StubRepo())
    for text in ("I want to buy a black iPhone 15 128GB under $900", "hmm I might get something for my sister later"):
        _, msgs = await handle(text, deps)
        print(f"   YOU: {text}\n   BOT: {msgs[-1].text[:90]}")


async def scenario_research(llm: LLM) -> None:
    from app.agents.researcher import MemoryResearchCache, ResearchDeps, research
    from app.research.fx import FxService
    from app.research.search import MemoryCreditStore, SearchBudget, TavilySearch

    s = get_settings()
    if not s.tavily_api_key:
        print("   (no TAVILY_API_KEY, research skipped)")
        return
    deps = ResearchDeps(llm=llm, search=TavilySearch(s.tavily_api_key), fx=FxService(), budget=SearchBudget(MemoryCreditStore(), s.tavily_monthly_cap), cache=MemoryResearchCache())
    r = await research("Dell XPS 15", ["16GB RAM"], "USD", deps)
    print(f"   research: available={r.available} median={r.median} credits={r.credits_used}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--with-research", action="store_true")
    args = ap.parse_args()
    DATA.mkdir(exist_ok=True)
    log_path = DATA / f"llm_usage_{args.label}.jsonl"
    log_path.write_text("")
    usage_log.path = str(log_path)
    s = get_settings()
    llm = LLM(s)  # no database budget: a local measurement
    print(f"Measuring with provider={s.llm_provider} model main={s.llm_model_main} fast={s.llm_model_fast} (label: {args.label})")
    results: dict = {"label": args.label, "provider": s.llm_provider, "model_main": s.llm_model_main, "model_fast": s.llm_model_fast, "scenarios": {}}
    steps = [("A_deal_3_vendors", scenario_deal), ("B_assistant", scenario_assistant)] + ([("C_research", scenario_research)] if args.with_research else [])
    for name, fn in steps:
        usage_log.records.clear()
        t = time.monotonic()
        print(f"== {name}")
        await fn(llm)
        results["scenarios"][name] = {**snapshot(), "seconds": round(time.monotonic() - t)}
        print(f"   -> {results['scenarios'][name]['calls']} calls, {results['scenarios'][name]['total']} tokens, {results['scenarios'][name]['seconds']} s")
    (DATA / f"token_run_{args.label}.json").write_text(json.dumps(results, indent=2))
    print("done. Run: uv run python scripts/token_report.py")


asyncio.run(main())
