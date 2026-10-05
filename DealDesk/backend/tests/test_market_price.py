import pytest
from fastapi.testclient import TestClient

from app.agents.assistant import Slots
from app.api.market import get_market_lookup
from app.core.config import get_settings
from app.research.market import advise, warning_for
from app.schemas.research import ResearchResult, Source
from main import app
from tests.test_assistant import ScriptLLM, make, say


def result(**kw):
    base = {
        "currency": "USD", "low": 999.0, "median": 1275.0, "high": 1552.0, "n_sources": 3, "confidence": "medium", "available": True,
        "sources": [Source(title="Shop", url="https://a.example.com", price=1275.0, region="US")],
    }  # fmt: skip
    return ResearchResult(**{**base, **kw})


def test_the_advice_gives_a_realistic_range_for_the_maximum():
    a = advise(result())
    assert a.available and a.range_min == 999 and a.range_max == 1275 and "$999" in a.text and "$1,275" in a.text
    assert a.sources and a.sources[0].url == "https://a.example.com"


def test_no_price_found_says_so_and_gives_no_range():
    a = advise(ResearchResult(currency="USD", available=False, reason="No usable prices were found."))
    assert not a.available and a.range_min is None and "could not find" in a.text


def test_a_maximum_below_the_lowest_market_price_gets_a_warning():
    a = advise(result())
    assert "very unlikely" in (warning_for(800, a) or "")
    assert warning_for(1100, a) is None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_enabled", True)

    async def lookup(item, must_haves, currency):
        assert item == "Dell XPS 15" and must_haves == ["16GB RAM"] and currency == "USD"
        return result()

    app.dependency_overrides[get_market_lookup] = lambda: lookup
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_endpoint_returns_the_range(client):
    r = client.post("/market-price", json={"item": "Dell XPS 15", "must_haves": ["16GB RAM"], "currency": "usd"}).json()
    assert r["available"] and r["range_min"] == 999 and r["range_max"] == 1275


def test_the_endpoint_needs_an_item(client):
    assert client.post("/market-price", json={"item": "  "}).status_code == 422


def test_the_endpoint_is_off_when_the_agent_is_off(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_enabled", False)
    assert client.post("/market-price", json={"item": "Dell XPS 15"}).status_code == 503


async def test_the_assistant_tells_you_the_market_price_before_asking_for_your_maximum():
    deps, _, _, _ = make()

    async def market(item, must_haves, currency):
        return result()

    deps.market = market
    deps.llm = ScriptLLM(slots=Slots(item="Dell XPS 15"))
    state, reply, _ = await say(deps, "I want to buy a Dell XPS 15")
    assert state.awaiting == "max_price" and "$999 to $1,552" in reply and "What is the most you would pay" in reply
    state, reply, _ = await say(deps, "800")
    assert "very unlikely" in reply and "Reply yes" in reply  # the warning, and you still decide


async def test_a_price_search_problem_never_breaks_the_chat():
    deps, _, _, _ = make()

    async def market(item, must_haves, currency):
        raise RuntimeError("search down")

    deps.market = market
    deps.llm = ScriptLLM(slots=Slots(item="Dell XPS 15"))
    state, reply, _ = await say(deps, "I want to buy a Dell XPS 15")
    assert state.awaiting == "max_price" and "What is the most you would pay" in reply


def test_a_very_wide_range_gets_a_warning_about_mixed_versions():
    assert "very wide" in advise(result(low=500.0, median=800.0, high=1300.0)).text
    assert "very wide" not in advise(result(high=1200.0)).text


def test_a_web_address_written_out_in_words_is_a_suspicious_link():
    from app.agents.safety_rules import scan, strongest

    assert strongest(scan("Check our catalogue on our website, just type techhubstore dot com.")[0]) == "suspicious_link"
    assert strongest(scan("I can do it for one hundred dot five dollars")[0]) == "ok"
