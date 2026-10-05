"""The model-call budget: a daily cap and a per-deal cap (CLAUDE.md section 7).

Every model call must pass `DealBudget.before_call` first. If a cap is reached the call is
refused and the model is never contacted. This is what stops one visitor, or one bug, from
using up the free tier of the model provider.

The count lives in Supabase (the `consume_llm_call` function in sql/002_functions.sql), so it
survives restarts and works across servers. If the count cannot be read we refuse the call
(fail closed), because an unchecked call could cost money or hit a provider limit.
"""

import asyncio
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Protocol

from app.core.config import Settings
from app.core.llm import BudgetExhausted, BudgetUnavailable

Status = Literal["ok", "daily_exhausted", "deal_exhausted", "unknown_deal"]


class BudgetStore(Protocol):
    def consume(self, day: str, deal_id: str | None, daily_cap: int, deal_cap: int) -> Status: ...


class SupabaseBudgetStore:
    def __init__(self, client) -> None:
        self.db = client

    def consume(self, day: str, deal_id: str | None, daily_cap: int, deal_cap: int) -> Status:
        res = self.db.rpc(
            "consume_llm_call",
            {"p_day": day, "p_deal_id": deal_id, "p_daily_cap": daily_cap, "p_deal_cap": deal_cap},
        ).execute()
        return res.data


class MemoryBudgetStore:
    """Counts in memory. Used in tests and in local development without a database."""

    def __init__(self) -> None:
        self.daily: dict[str, int] = {}
        self.deals: dict[str, int] = {}
        self._lock = threading.Lock()

    def consume(self, day: str, deal_id: str | None, daily_cap: int, deal_cap: int) -> Status:
        with self._lock:
            if deal_id is not None and self.deals.get(deal_id, 0) >= deal_cap:
                return "deal_exhausted"
            if self.daily.get(day, 0) >= daily_cap:
                return "daily_exhausted"
            self.daily[day] = self.daily.get(day, 0) + 1
            if deal_id is not None:
                self.deals[deal_id] = self.deals.get(deal_id, 0) + 1
            return "ok"


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


class DealBudget:
    """Plugs into LLM as its BudgetGuard."""

    def __init__(self, store: BudgetStore, daily_cap: int, deal_cap: int, today: Callable[[], str] = _today) -> None:
        self.store = store
        self.daily_cap = daily_cap
        self.deal_cap = deal_cap
        self._today = today

    async def before_call(self, deal_id: str | None) -> None:
        try:
            # The store is synchronous (the database client is), so run it off the event loop.
            status = await asyncio.to_thread(self.store.consume, self._today(), deal_id, self.daily_cap, self.deal_cap)
        except Exception as e:
            raise BudgetUnavailable("The call budget could not be checked.") from e

        if status == "ok":
            return
        if status == "daily_exhausted":
            raise BudgetExhausted("Demo limit reached, try tomorrow.", reason="daily")
        if status == "deal_exhausted":
            raise BudgetExhausted("This deal has used its model-call limit.", reason="deal")
        raise BudgetUnavailable(f"The call budget could not be checked ({status}).")


def make_budget(settings: Settings) -> DealBudget:
    """Supabase when it is configured, memory otherwise (local development)."""
    if settings.supabase_url and settings.supabase_service_role_key:
        from app.core.db import get_client

        store: BudgetStore = SupabaseBudgetStore(get_client())
    else:
        store = MemoryBudgetStore()
    return DealBudget(store, settings.daily_llm_call_budget, settings.max_llm_calls_per_deal)
