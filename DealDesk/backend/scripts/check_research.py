"""Runs the Researcher for REAL: real web search (Tavily), real model, real exchange rates.

Run from backend/:  uv run python scripts/check_research.py
It spends a handful of Tavily credits (about 5 per product). Credits are counted in memory here,
so the real monthly counter is not touched. Look at the results with your own eyes: the code can
check that prices are written in the text, but only a human can say if the range is sensible.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from app.agents.researcher import (
    MemoryResearchCache,
    ResearchDeps,
    describe,
    research,
)
from app.core.config import get_settings
from app.core.llm import get_llm
from app.core.money import format_price
from app.research.fx import FxService
from app.research.search import (
    MemoryCreditStore,
    SearchBudget,
    TavilySearch,
)

PRODUCTS = [
    ("Dell XPS 15", ["16GB RAM"], "USD"),
    ("iPhone 15 128GB", [], "PKR"),
    ("Sony WH-1000XM5 headphones", [], "USD"),
]


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="   [%(asctime)s] %(name)s %(message)s", datefmt="%H:%M:%S")
    only = int(sys.argv[1]) if len(sys.argv) > 1 else None  # run just one product: python scripts/check_research.py 0
    s = get_settings()
    if not s.tavily_api_key:
        print("TAVILY_API_KEY is empty in backend/.env")
        return 1
    deps = ResearchDeps(
        llm=get_llm(),
        search=TavilySearch(s.tavily_api_key),
        fx=FxService(),
        budget=SearchBudget(MemoryCreditStore(), s.tavily_monthly_cap),
        cache=MemoryResearchCache(),
    )
    total_credits = 0
    for n, (item, must, cur) in enumerate(PRODUCTS):
        if only is not None and n != only:
            continue
        t0 = time.time()
        r = await research(item, must, cur, deps)
        total_credits += r.credits_used
        print("=" * 100)
        print(f"{item} {must or ''} in {cur}   ({time.time() - t0:.0f}s, {r.credits_used} credits)")
        print("  ", describe(r)[0])
        if r.available:
            print(f"   low {format_price(r.low, cur)}  median {format_price(r.median, cur)}  high {format_price(r.high, cur)}"
                  f"  | {r.n_sources} websites | regions {r.regions} | outliers removed {r.outliers_removed}")
            for src in sorted(r.sources, key=lambda x: x.price):
                print(f"     {format_price(src.price, cur):>14}  {src.region:9} {src.url[:70]}")
        else:
            print("   reason:", r.reason)
        if r.reason and r.available:
            print("   note:", r.reason)
        print("  ", r.fx_note)
    print("=" * 100)
    print(f"total Tavily credits used by this run: {total_credits}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
