"""Builds the real Runtime: the real model, Supabase and web search. Only the API and the server start-up import this.

Nothing here runs until `get_runtime()` is called, so importing the app never needs a database or a key.
"""

import asyncio
from functools import lru_cache

from app.agents.manager import ManagerDeps
from app.agents.researcher import ResearchDeps, SupabaseResearchCache, research
from app.agents.runtime import Runtime, build_runtime, demo_delay
from app.core.config import get_settings
from app.core.db import SupabaseDealStore, get_client
from app.core.llm import get_llm
from app.research.fx import FxService
from app.research.search import SearchBudget, SupabaseCreditStore, TavilySearch
from app.schemas.records import DealRecord
from app.schemas.research import ResearchResult


@lru_cache
def get_research_deps() -> ResearchDeps:
    s = get_settings()
    client = get_client()
    return ResearchDeps(
        llm=get_llm(),
        search=TavilySearch(s.tavily_api_key),
        fx=FxService(),
        budget=SearchBudget(SupabaseCreditStore(client), s.tavily_monthly_cap),
        cache=SupabaseResearchCache(client),
    )


async def lookup_market(item: str, must_haves: list[str], currency: str) -> ResearchResult:
    """The market price BEFORE a deal exists (to help you choose your maximum). It uses the same cache key as the deal's own
    research, so starting the deal afterwards reuses this result and spends no extra search credits."""
    if get_settings().research_mode == "fixed":
        from app.simulator.scripted_llm import fixed_research

        return await fixed_research(DealRecord(id="preview", item=item, max_price=800.0, currency=currency, must_haves=must_haves, address=""))
    return await research(item, must_haves, currency, get_research_deps(), None)


@lru_cache
def get_runtime() -> Runtime:
    s = get_settings()
    client = get_client()
    store = SupabaseDealStore(client)
    llm = get_llm()
    deps = get_research_deps()

    async def research_fn(deal: DealRecord) -> ResearchResult:
        if s.research_mode == "fixed":  # playing around: a demo market price, no web search, no Tavily credits
            from app.simulator.scripted_llm import fixed_research

            return await fixed_research(deal)
        # The market price is searched for the MODEL, not for the exact color or storage: listings differ by variant, and asking for one
        # variant made every listing "not a match" (a real run for an Infinix phone found no price). The variant is used when reading vendor prices.
        return await research(deal.item, deal.must_haves, deal.currency, deps, deal.id)

    async def find_deal(vendor_id: str) -> str | None:
        rows = await asyncio.to_thread(lambda: client.table("vendors").select("deal_id").eq("id", vendor_id).limit(1).execute().data)
        return rows[0]["deal_id"] if rows else None

    runtime = build_runtime(
        store,
        lambda rt: ManagerDeps(llm=llm, store=store, research=research_fn, on_send=rt.on_send),  # type: ignore[arg-type]
        find_deal,
        demo_delay,
    )
    return runtime
