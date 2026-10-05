import pytest

from app.research.fx import (
    FALLBACK_RATES,
    FxService,
    RateTable,
    UnsupportedCurrency,
    _validated,
    convert,
    fallback_table,
)

LIVE = {"USD": 1.0, "PKR": 280.0, "AED": 3.6725, "GBP": 0.75, "EUR": 0.88, "SAR": 3.75}


def table(rates=None) -> RateTable:
    return RateTable(rates=rates or dict(LIVE), as_of="2026-10-02", source="live", origin="test")


# ---------------------------------------------------------------- converting


def test_converting_through_the_dollar():
    t = table()
    assert convert(100, "USD", "PKR", t) == pytest.approx(28000)
    assert convert(28000, "PKR", "USD", t) == pytest.approx(100)
    assert convert(100, "GBP", "EUR", t) == pytest.approx(100 / 0.75 * 0.88)


def test_same_currency_is_unchanged():
    assert convert(123.45, "AED", "AED", table()) == pytest.approx(123.45)


def test_currency_codes_are_case_insensitive():
    assert convert(10, "usd", "eur", table()) == pytest.approx(8.8)


def test_an_unknown_currency_is_refused_not_guessed():
    with pytest.raises(UnsupportedCurrency):
        convert(10, "JPY", "USD", table())


# ---------------------------------------------------------------- sources and fallback


def make_fetcher(result):
    calls = {"n": 0}

    async def fetch():
        calls["n"] += 1
        if isinstance(result, Exception):
            raise result
        return result

    fetch.calls = calls
    return fetch


async def test_the_first_working_source_is_used():
    f1, f2 = make_fetcher(table()), make_fetcher(table())
    got = await FxService((f1, f2)).table()
    assert got.source == "live" and f1.calls["n"] == 1 and f2.calls["n"] == 0


async def test_the_second_source_is_used_when_the_first_fails():
    f1, f2 = make_fetcher(ConnectionError("down")), make_fetcher(table())
    assert (await FxService((f1, f2)).table()).source == "live"


async def test_the_built_in_table_is_used_when_every_source_fails():
    got = await FxService((make_fetcher(ValueError("x")), make_fetcher(ConnectionError("y")))).table()
    assert got.source == "fallback" and got.rates == FALLBACK_RATES
    assert "approximate" in got.describe() and got.as_of in got.describe()


async def test_live_rates_are_cached_for_a_day():
    f = make_fetcher(table())
    now = [1000.0]
    svc = FxService((f,), clock=lambda: now[0])
    await svc.table()
    now[0] += 3600
    await svc.table()
    assert f.calls["n"] == 1
    now[0] += 24 * 3600
    await svc.table()
    assert f.calls["n"] == 2


async def test_the_fallback_is_retried_soon_so_the_app_recovers():
    f = make_fetcher(ConnectionError("down"))
    now = [0.0]
    svc = FxService((f,), clock=lambda: now[0])
    await svc.table()
    now[0] += 20 * 60
    await svc.table()
    assert f.calls["n"] == 2


# ---------------------------------------------------------------- guarding against bad data


def test_a_missing_currency_rejects_the_whole_source():
    bad = dict(LIVE)
    del bad["PKR"]
    with pytest.raises(ValueError):
        _validated(bad, "d", "src")


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), "abc", None])
def test_nonsense_rates_are_rejected(value):
    with pytest.raises(ValueError):
        _validated({**LIVE, "PKR": value}, "d", "src")


def test_a_rate_far_from_reality_is_rejected():
    with pytest.raises(ValueError):
        _validated({**LIVE, "PKR": 2.8}, "d", "src")  # a decimal-point glitch would turn $700 into 1,960 rupees


def test_the_built_in_table_covers_every_supported_currency_and_passes_its_own_check():
    t = fallback_table()
    assert set(t.rates) == {"USD", "PKR", "AED", "GBP", "EUR", "SAR"}
    _validated(t.rates, t.as_of, "built-in")
