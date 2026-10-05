import pytest
from fastapi.testclient import TestClient

from app.agents.assistant import Slots
from app.api.parse import get_parse_llm
from app.core.llm import usage_log
from main import app
from tests.test_assistant import ScriptLLM


def client(llm):
    app.dependency_overrides[get_parse_llm] = lambda: llm
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()


def test_a_sentence_becomes_form_fields():
    llm = ScriptLLM(slots=Slots(item="iPhone 15", variant="black 128GB", must_haves=["a charger"]))
    r = client(llm).post("/parse-request", json={"text": "I want to buy a black iPhone 15 128GB under $900 with a charger"}).json()
    assert r == {
        "item": "iPhone 15", "variant": "black 128GB", "max_price": 900, "currency": "USD", "must_haves": ["a charger"],
        "understood": True, "note": "Check every field before you start.",
    }  # fmt: skip


def test_the_price_comes_from_the_parser_never_from_the_model():
    llm = ScriptLLM(slots=Slots(item="Dell XPS 15", max_price=5000))
    r = client(llm).post("/parse-request", json={"text": "Dell XPS 15, my budget is $800"}).json()
    assert r["max_price"] == 800


def test_words_the_model_invented_are_dropped():
    llm = ScriptLLM(slots=Slots(item="MacBook", variant="gold", must_haves=["free yacht"]))
    r = client(llm).post("/parse-request", json={"text": "I want to buy a Dell XPS 15 under $800"}).json()
    assert r["item"] == "" and r["variant"] == "" and r["must_haves"] == [] and r["understood"] is False and "could not find" in r["note"]
    assert r["max_price"] == 800  # the price is still found by code


def test_two_prices_without_a_clue_leave_the_maximum_empty_and_say_so():
    llm = ScriptLLM(slots=Slots(item="Dell XPS 15"))
    r = client(llm).post("/parse-request", json={"text": "Dell XPS 15, between $700 and $900"}).json()
    assert r["max_price"] is None and "more than one price" in r["note"] and r["item"] == "Dell XPS 15"


def test_no_price_at_all():
    r = client(ScriptLLM(slots=Slots(item="Dell XPS 15"))).post("/parse-request", json={"text": "I want a Dell XPS 15"}).json()
    assert r["max_price"] is None and "did not find a maximum price" in r["note"]


def test_the_currency_is_read_from_your_words():
    llm = ScriptLLM(slots=Slots(item="iPhone 15"))
    assert client(llm).post("/parse-request", json={"text": "iPhone 15 under PKR 250,000"}).json()["currency"] == "PKR"
    assert client(llm).post("/parse-request", json={"text": "iPhone 15 under £700"}).json()["currency"] == "GBP"


def test_when_the_model_fails_the_code_still_finds_the_price_and_currency():
    r = client(ScriptLLM(fail=True)).post("/parse-request", json={"text": "I want a Dell XPS 15 under $800"})
    assert r.status_code == 200 and r.json()["max_price"] == 800 and r.json()["understood"] is False


def test_it_starts_nothing_and_touches_no_database():
    llm = ScriptLLM(slots=Slots(item="Dell XPS 15"))
    client(llm).post("/parse-request", json={"text": "I want to buy a Dell XPS 15 under $800"})
    assert llm.calls == ["Slots"]  # one model read, nothing else


def test_validation():
    c = client(ScriptLLM())
    assert c.post("/parse-request", json={"text": "   "}).status_code == 422
    assert c.post("/parse-request", json={"text": "x" * 501}).status_code == 422
    assert c.post("/parse-request", json={}).status_code == 422


async def test_the_token_log_names_the_agent():
    from app.agents.assistant import read_slots

    usage_log.records.clear()
    from tests.test_usage import Client, make, reply

    llm = make(Client([reply('{"item": "Dell", "variant": "", "max_price": null, "currency": "", "must_haves": []}', 50, 10)]))
    await read_slots("I want a Dell", llm, "USD", agent="Parse request")
    assert usage_log.records[0].agent == "Parse request"
    usage_log.records.clear()
