"""Web search through Tavily, with a monthly credit cap.

Tavily's free plan is 1,000 credits a month and a basic search costs 1. We count every search against
a cap (TAVILY_MONTHLY_CAP, 800 by default) BEFORE making it, so we can never run past the free plan.
If the cap is reached or the search fails, the Researcher reports "research unavailable" and the
agent asks the user. It never makes up a price.
"""

import asyncio
import threading
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel


class SearchError(Exception):
    pass


class SearchBudgetExhausted(SearchError):
    """The monthly credit cap is reached. No search was made."""


class SearchUnavailable(SearchError):
    """The search service failed, or the credits could not be counted. Fail closed."""


class SearchHit(BaseModel):
    title: str
    url: str
    content: str


class SearchProvider(Protocol):
    async def search(self, query: str, country: str | None, max_results: int) -> list[SearchHit]: ...


class TavilySearch:
    def __init__(self, api_key: str) -> None:
        from tavily import AsyncTavilyClient

        self.client = AsyncTavilyClient(api_key=api_key)

    async def search(self, query: str, country: str | None = None, max_results: int = 5) -> list[SearchHit]:
        kwargs = {"query": query, "search_depth": "basic", "max_results": max_results}  # basic = 1 credit
        try:
            try:
                res = await self.client.search(**kwargs, country=country) if country else await self.client.search(**kwargs)
            except Exception as e:
                # Some country names are rejected. Try once more without the country.
                if country and "country" in str(e).lower():
                    res = await self.client.search(**kwargs)
                else:
                    raise
        except Exception as e:
            raise SearchUnavailable(f"Search failed ({type(e).__name__})") from e
        return [
            SearchHit(title=str(r.get("title") or ""), url=str(r.get("url") or ""), content=str(r.get("content") or ""))
            for r in res.get("results", [])
            if r.get("url")
        ]


# ---------------------------------------------------------------- the monthly credit cap

CreditStatus = Literal["ok", "monthly_exhausted"]


class CreditStore(Protocol):
    def consume(self, day: str, amount: int, monthly_cap: int) -> CreditStatus: ...


class MemoryCreditStore:
    def __init__(self) -> None:
        self.by_day: dict[str, int] = {}
        self._lock = threading.Lock()

    def consume(self, day: str, amount: int, monthly_cap: int) -> CreditStatus:
        month = day[:7]
        with self._lock:
            used = sum(v for d, v in self.by_day.items() if d[:7] == month)
            if used + amount > monthly_cap:
                return "monthly_exhausted"
            self.by_day[day] = self.by_day.get(day, 0) + amount
            return "ok"


class SupabaseCreditStore:
    def __init__(self, client) -> None:
        self.db = client

    def consume(self, day: str, amount: int, monthly_cap: int) -> CreditStatus:
        res = self.db.rpc("consume_search_credits", {"p_day": day, "p_amount": amount, "p_monthly_cap": monthly_cap}).execute()
        return res.data


class SearchBudget:
    def __init__(self, store: CreditStore, monthly_cap: int, today=lambda: datetime.now(UTC).date().isoformat()) -> None:
        self.store = store
        self.monthly_cap = monthly_cap
        self._today = today

    async def consume(self, amount: int = 1) -> None:
        try:
            status = await asyncio.to_thread(self.store.consume, self._today(), amount, self.monthly_cap)
        except Exception as e:
            raise SearchUnavailable("The search credits could not be counted.") from e
        if status != "ok":
            raise SearchBudgetExhausted("The monthly search limit is reached.")
