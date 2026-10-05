import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.budget import (
    DealBudget,
    MemoryBudgetStore,
    SupabaseBudgetStore,
    make_budget,
)
from app.core.config import Settings
from app.core.llm import LLM, BudgetExhausted, BudgetUnavailable


def budget(daily=10, deal=5, today=lambda: "2026-10-02") -> tuple[DealBudget, MemoryBudgetStore]:
    store = MemoryBudgetStore()
    return DealBudget(store, daily, deal, today), store


# ---------------------------------------------------------------- the two caps


async def test_calls_are_allowed_until_the_daily_cap():
    b, _ = budget(daily=3)
    for _ in range(3):
        await b.before_call(None)
    with pytest.raises(BudgetExhausted) as e:
        await b.before_call(None)
    assert e.value.reason == "daily" and "try tomorrow" in str(e.value)


async def test_one_deal_cannot_use_more_than_its_own_cap():
    b, _ = budget(daily=100, deal=2)
    await b.before_call("deal-a")
    await b.before_call("deal-a")
    with pytest.raises(BudgetExhausted) as e:
        await b.before_call("deal-a")
    assert e.value.reason == "deal"
    await b.before_call("deal-b")  # another deal is not affected


async def test_a_refused_call_is_not_counted():
    b, store = budget(daily=2, deal=1)
    await b.before_call("d")
    with pytest.raises(BudgetExhausted):
        await b.before_call("d")  # refused by the deal cap
    assert store.daily["2026-10-02"] == 1  # the refused call did not use up the daily budget
    await b.before_call("other")  # still room for one more today


async def test_calls_without_a_deal_only_count_against_the_day():
    b, store = budget(daily=2, deal=1)
    await b.before_call(None)
    await b.before_call(None)
    assert store.deals == {}


async def test_the_budget_starts_again_on_a_new_day():
    day = ["2026-10-02"]
    b, _ = budget(daily=1, today=lambda: day[0])
    await b.before_call(None)
    with pytest.raises(BudgetExhausted):
        await b.before_call(None)
    day[0] = "2026-10-03"
    await b.before_call(None)


async def test_overlapping_calls_never_go_over_the_cap():
    b, _ = budget(daily=10)
    results = await asyncio.gather(*[b.before_call(None) for _ in range(60)], return_exceptions=True)
    assert sum(r is None for r in results) == 10
    assert sum(isinstance(r, BudgetExhausted) for r in results) == 50


# ---------------------------------------------------------------- failing closed


async def test_if_the_count_cannot_be_read_the_call_is_refused():
    class Broken:
        def consume(self, *a):
            raise ConnectionError("database down")

    b = DealBudget(Broken(), 10, 5)
    with pytest.raises(BudgetUnavailable):
        await b.before_call("d")


async def test_an_unknown_deal_is_refused():
    class Unknown:
        def consume(self, *a):
            return "unknown_deal"

    with pytest.raises(BudgetUnavailable):
        await DealBudget(Unknown(), 10, 5).before_call("nope")


# ---------------------------------------------------------------- plugged into the model layer


class FakeClient:
    def __init__(self):
        self.calls = 0
        reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))])

        async def create(**kwargs):
            self.calls += 1
            return reply

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


async def test_the_model_is_not_called_once_the_budget_is_used_up():
    client = FakeClient()
    b, _ = budget(daily=100, deal=2)
    llm = LLM(Settings(_env_file=None), client=client, budget=b)
    await llm.complete("fast", "s", "u", deal_id="d1")
    await llm.complete("fast", "s", "u", deal_id="d1")
    with pytest.raises(BudgetExhausted):
        await llm.complete("fast", "s", "u", deal_id="d1")
    assert client.calls == 2  # the third call never reached the model


# ---------------------------------------------------------------- the real store and wiring


def test_the_database_store_sends_the_right_arguments_and_returns_the_status():
    sent = {}

    class Rpc:
        def execute(self):
            return SimpleNamespace(data="ok")

    class Client:
        def rpc(self, name, args):
            sent.update(name=name, args=args)
            return Rpc()

    status = SupabaseBudgetStore(Client()).consume("2026-10-02", "deal-1", 600, 100)
    assert status == "ok"
    assert sent == {
        "name": "consume_llm_call",
        "args": {"p_day": "2026-10-02", "p_deal_id": "deal-1", "p_daily_cap": 600, "p_deal_cap": 100},
    }


def test_without_a_database_the_budget_counts_in_memory():
    b = make_budget(Settings(_env_file=None, supabase_url="", supabase_service_role_key=""))
    assert isinstance(b.store, MemoryBudgetStore)


def test_the_budget_uses_the_caps_from_settings():
    b = make_budget(Settings(_env_file=None, daily_llm_call_budget=7, max_llm_calls_per_deal=3))
    assert (b.daily_cap, b.deal_cap) == (7, 3)


def test_the_sql_function_is_locked_to_the_server_and_counts_atomically():
    sql = (Path(__file__).resolve().parent.parent / "sql" / "002_functions.sql").read_text()
    assert "revoke all on function consume_llm_call" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert "for update" in sql  # row locks make the count exact


def test_the_api_answers_429_when_the_budget_is_used_up():
    from main import budget_exhausted, budget_unavailable

    app = FastAPI()
    app.add_exception_handler(BudgetExhausted, budget_exhausted)
    app.add_exception_handler(BudgetUnavailable, budget_unavailable)

    @app.get("/daily")
    def daily():
        raise BudgetExhausted()

    @app.get("/deal")
    def deal():
        raise BudgetExhausted("This deal has used its model-call limit.", reason="deal")

    @app.get("/down")
    def down():
        raise BudgetUnavailable("x")

    c = TestClient(app)
    r = c.get("/daily")
    assert r.status_code == 429 and r.json()["error"] == "budget_exhausted" and r.json()["reason"] == "daily"
    assert c.get("/deal").json()["reason"] == "deal"
    assert c.get("/down").status_code == 503
