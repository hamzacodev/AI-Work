import asyncio

import pytest

from app.research.search import (
    MemoryCreditStore,
    SearchBudget,
    SearchBudgetExhausted,
    SearchUnavailable,
    SupabaseCreditStore,
    TavilySearch,
)


def budget(cap=5, day="2026-10-02", store=None):
    return SearchBudget(store or MemoryCreditStore(), cap, today=lambda: day), store


# ---------------------------------------------------------------- the monthly credit cap


async def test_searches_are_allowed_up_to_the_monthly_cap():
    b, _ = budget(3)
    for _ in range(3):
        await b.consume(1)
    with pytest.raises(SearchBudgetExhausted):
        await b.consume(1)


async def test_the_cap_covers_the_whole_month_not_one_day():
    store = MemoryCreditStore()
    day = ["2026-10-02"]
    b = SearchBudget(store, 3, today=lambda: day[0])
    await b.consume(2)
    day[0] = "2026-10-20"
    await b.consume(1)
    with pytest.raises(SearchBudgetExhausted):
        await b.consume(1)


async def test_a_new_month_starts_fresh():
    store = MemoryCreditStore()
    day = ["2026-10-30"]
    b = SearchBudget(store, 2, today=lambda: day[0])
    await b.consume(2)
    day[0] = "2026-11-01"
    await b.consume(1)


async def test_a_refused_request_is_not_counted():
    store = MemoryCreditStore()
    b = SearchBudget(store, 3, today=lambda: "2026-10-02")
    await b.consume(2)
    with pytest.raises(SearchBudgetExhausted):
        await b.consume(2)  # would make 4
    await b.consume(1)  # the refused 2 were not used up


async def test_overlapping_searches_never_pass_the_cap():
    b, _ = budget(10)
    results = await asyncio.gather(*[b.consume(1) for _ in range(40)], return_exceptions=True)
    assert sum(r is None for r in results) == 10


async def test_if_the_credits_cannot_be_counted_the_search_is_refused():
    class Broken:
        def consume(self, *a):
            raise ConnectionError("db down")

    with pytest.raises(SearchUnavailable):
        await SearchBudget(Broken(), 5).consume(1)


def test_the_database_store_sends_the_right_arguments():
    sent = {}

    class Rpc:
        def execute(self):
            from types import SimpleNamespace

            return SimpleNamespace(data="ok")

    class Client:
        def rpc(self, name, args):
            sent.update(name=name, args=args)
            return Rpc()

    assert SupabaseCreditStore(Client()).consume("2026-10-02", 1, 800) == "ok"
    assert sent == {"name": "consume_search_credits", "args": {"p_day": "2026-10-02", "p_amount": 1, "p_monthly_cap": 800}}


def test_the_sql_function_is_locked_to_the_server():
    from pathlib import Path

    sql = (Path(__file__).resolve().parent.parent / "sql" / "003_search_credits.sql").read_text()
    assert "from public, anon, authenticated" in sql and "to service_role" in sql
    assert "pg_advisory_xact_lock" in sql


# ---------------------------------------------------------------- the Tavily wrapper


class FakeTavily:
    def __init__(self, response=None, error=None, reject_country=False):
        self.response = response if response is not None else {"results": []}
        self.error = error
        self.reject_country = reject_country
        self.calls: list[dict] = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject_country and "country" in kwargs:
            raise ValueError("invalid country name")
        if self.error:
            raise self.error
        return self.response


def wrapper(fake) -> TavilySearch:
    t = TavilySearch.__new__(TavilySearch)
    t.client = fake
    return t


async def test_a_basic_search_is_requested_so_it_costs_one_credit():
    fake = FakeTavily({"results": [{"title": "T", "url": "https://a.example.com", "content": "c"}]})
    hits = await wrapper(fake).search("dell xps 15 price", "united states", 5)
    assert fake.calls[0]["search_depth"] == "basic" and fake.calls[0]["max_results"] == 5
    assert fake.calls[0]["country"] == "united states"
    assert [h.url for h in hits] == ["https://a.example.com"]


async def test_results_without_a_link_are_ignored():
    fake = FakeTavily({"results": [{"title": "no link", "content": "x"}, {"title": "ok", "url": "https://a.example.com", "content": "y"}]})
    assert len(await wrapper(fake).search("q", None, 5)) == 1


async def test_a_rejected_country_is_retried_without_it():
    fake = FakeTavily({"results": [{"title": "T", "url": "https://a.example.com", "content": "c"}]}, reject_country=True)
    hits = await wrapper(fake).search("q", "atlantis", 5)
    assert len(hits) == 1 and "country" not in fake.calls[-1]


async def test_a_failing_search_becomes_search_unavailable():
    with pytest.raises(SearchUnavailable):
        await wrapper(FakeTavily(error=RuntimeError("boom"))).search("q", None, 5)
