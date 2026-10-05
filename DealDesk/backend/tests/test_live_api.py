import uuid

import pytest
from fastapi.testclient import TestClient

from app.agents.fact_rules import Turn
from app.agents.manager import ManagerDeps
from app.agents.runtime import build_runtime, persona_for
from app.api.deals import build_summary, get_agent_runtime, maybe_agent_runtime
from app.core import resume
from app.core.config import get_settings
from app.core.db import get_repo
from app.schemas.records import DealRecord, InMemoryDealStore, VendorRecord
from main import app
from tests.test_deals_api import FakeRepo, payload
from tests.test_manager import FakeLLM, research


@pytest.fixture
def agent():
    """A real Runtime with a fake model and an in-memory store, plugged into the API."""
    store = InMemoryDealStore()
    deal = DealRecord(id=str(uuid.uuid4()), item="Dell XPS 15", max_price=800.0, address="12 Example Street")
    for i, n in enumerate(("Alpha", "Beta")):
        vid = str(uuid.uuid4())
        deal.vendors[vid] = VendorRecord(vid, n, f"{n.lower()}@shop.example.com", persona=persona_for(i))
    store.add(deal)
    runtime = build_runtime(store, lambda rt: ManagerDeps(llm=FakeLLM(), store=store, research=research(), on_send=rt.on_send))
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    yield runtime, deal
    app.dependency_overrides.clear()


def ids(deal):
    return deal.id, list(deal.vendors)


# ---------------------------------------------------------------- take control


def test_switching_a_vendor_to_you(agent):
    _, deal = agent
    deal_id, (a, _) = ids(deal)
    r = TestClient(app).post(f"/deals/{deal_id}/vendors/{a}/control", json={"played_by": "you"})
    assert r.status_code == 200 and r.json() == {"played_by": "you"} and deal.vendors[a].played_by == "you"


def test_control_rejects_unknown_values_vendors_and_ids(agent):
    _, deal = agent
    deal_id, (a, _) = ids(deal)
    c = TestClient(app)
    assert c.post(f"/deals/{deal_id}/vendors/{a}/control", json={"played_by": "robot"}).status_code == 422
    assert c.post(f"/deals/{deal_id}/vendors/{uuid.uuid4()}/control", json={"played_by": "you"}).status_code == 404
    assert c.post(f"/deals/{uuid.uuid4()}/vendors/{a}/control", json={"played_by": "you"}).status_code == 404
    assert c.post(f"/deals/{deal_id}/vendors/not-a-uuid/control", json={"played_by": "you"}).status_code == 422


async def _settle():
    while resume._tasks:
        await resume.wait_for_tasks()


def test_typing_as_the_vendor_needs_the_you_switch(agent):
    _, deal = agent
    deal_id, (a, _) = ids(deal)
    r = TestClient(app).post(f"/deals/{deal_id}/vendors/{a}/message", json={"text": "$880"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "not_your_vendor"


def test_a_message_typed_as_the_vendor_is_accepted_and_the_agent_answers(agent):
    _, deal = agent
    deal_id, (a, _) = ids(deal)
    deal.vendors[a].played_by = "you"
    deal.vendors[a].conversation.append(Turn(sender="agent", text="Hello, what is your best price?"))
    with TestClient(app) as c:  # the context keeps one event loop alive, so the background task can finish
        r = c.post(f"/deals/{deal_id}/vendors/{a}/message", json={"text": "$880, ready to ship"})
        assert r.status_code == 202 and r.json() == {"accepted": True}
        import time

        for _ in range(50):
            if len(deal.vendors[a].conversation) >= 3:
                break
            time.sleep(0.05)
    assert [t.sender for t in deal.vendors[a].conversation] == ["agent", "vendor", "agent"]


def test_empty_vendor_messages_are_rejected(agent):
    _, deal = agent
    deal_id, (a, _) = ids(deal)
    deal.vendors[a].played_by = "you"
    assert TestClient(app).post(f"/deals/{deal_id}/vendors/{a}/message", json={"text": "   "}).status_code == 422


def test_without_agent_enabled_the_agent_endpoints_say_so():
    app.dependency_overrides.clear()
    assert not get_settings().agent_enabled
    r = TestClient(app).post(f"/deals/{uuid.uuid4()}/vendors/{uuid.uuid4()}/control", json={"played_by": "you"})
    assert r.status_code == 503 and r.json()["detail"]["error"] == "agent_disabled"


# ---------------------------------------------------------------- creating a deal and reading it


@pytest.fixture
def repo():
    r = FakeRepo()
    app.dependency_overrides[get_repo] = lambda: r
    yield r
    app.dependency_overrides.pop(get_repo, None)


def test_creating_a_deal_gives_each_vendor_a_fake_personality(repo):
    r = TestClient(app).post("/deals", json=payload())
    assert r.status_code == 201
    vendors = repo.deals[r.json()["id"]]["vendors"]
    assert [v["persona"] for v in vendors][:2] == ["friendly", "pushy"]


def test_creating_a_deal_starts_the_agent_only_when_it_is_enabled(repo, monkeypatch):
    started = []

    class Fake:
        async def start_deal(self, deal_id):
            started.append(deal_id)

    monkeypatch.setattr(get_settings(), "agent_enabled", False)
    TestClient(app).post("/deals", json=payload())  # the real maybe_agent_runtime returns None when the agent is off
    assert started == []
    app.dependency_overrides[maybe_agent_runtime] = lambda: Fake()
    with TestClient(app) as c:
        deal_id = c.post("/deals", json=payload()).json()["id"]
        import time

        for _ in range(50):
            if started:
                break
            time.sleep(0.05)
    assert started == [deal_id]
    app.dependency_overrides.clear()


def row(vid, name, price, status="negotiating", **over):
    return {"id": vid, "name": name, "channel": "email", "status": status, "offer_price": price, "recommendation": None, "messages": [], "events": [], **over}


def test_reading_a_deal_shows_the_best_deal_so_far(repo):
    repo.deals["d"] = {
        "id": "d", "item": "Dell XPS 15", "max_price": 800, "currency": "USD", "status": "created",
        "research": {"available": True, "median": 700, "low": 640, "high": 790},
        "vendors": [row("a", "Alpha", 840, "paused", stop_reason="firm_price", firm=True), row("b", "Beta", 650, "paused"), row("c", "Gamma", 620, "negotiating")],
    }  # fmt: skip
    deal_id = str(uuid.uuid4())
    repo.deals[deal_id] = repo.deals.pop("d")
    body = TestClient(app).get(f"/deals/{deal_id}").json()
    s = body["summary"]
    assert s["best_vendor_id"] == "c" and s["best_price"] == 620 and s["saved"] == 80 and not s["all_done"] and s["still_negotiating"] == 1
    assert [r["name"] for r in s["ranking"]] == ["Gamma", "Beta", "Alpha"]
    assert body["vendors"][0]["status"] == "paused" and body["vendors"][0]["firm"] and body["vendors"][0]["stop_reason"] == "firm_price"
    assert "address" not in body and "phone" not in body


def test_the_summary_without_research_has_no_savings_and_no_crash():
    s = build_summary({"currency": "USD", "research": None, "vendors": [row("a", "Alpha", 700)]})
    assert s.best_price == 700 and s.saved is None


def test_a_deal_with_no_vendors_has_no_summary():
    assert build_summary({"currency": "USD", "vendors": []}) is None


def test_messages_show_whether_a_fake_vendor_wrote_them(repo):
    deal_id = str(uuid.uuid4())
    repo.deals[deal_id] = {
        "id": deal_id, "item": "x", "max_price": 1, "currency": "USD", "status": "created", "research": None,
        "vendors": [row("a", "Alpha", None, messages=[{"from": "vendor", "text": "$900", "simulated": True, "at": "2026-10-02T10:00:00Z"}, {"from": "agent", "text": "Hi", "at": "2026-10-02T10:00:01Z"}])],
    }  # fmt: skip
    msgs = TestClient(app).get(f"/deals/{deal_id}").json()["vendors"][0]["messages"]
    assert [m["simulated"] for m in msgs] == [True, False]


# ---------------------------------------------------------------- choosing which vendors you play


def test_you_can_take_control_of_only_the_vendors_you_choose(agent):
    _, deal = agent
    deal_id, (a, b) = ids(deal)
    r = TestClient(app).post(f"/deals/{deal_id}/control", json={"vendor_ids": [a], "played_by": "you"})
    assert r.status_code == 200 and r.json() == {"updated": 1, "played_by": "you"}
    assert deal.vendors[a].played_by == "you" and deal.vendors[b].played_by == "simulator"  # Beta is untouched


def test_you_can_take_control_of_several_and_hand_some_back(agent):
    _, deal = agent
    deal_id, (a, b) = ids(deal)
    c = TestClient(app)
    assert c.post(f"/deals/{deal_id}/control", json={"vendor_ids": [a, b, a], "played_by": "you"}).json()["updated"] == 2
    assert {v.played_by for v in deal.vendors.values()} == {"you"}
    c.post(f"/deals/{deal_id}/control", json={"vendor_ids": [b], "played_by": "simulator"})
    assert deal.vendors[a].played_by == "you" and deal.vendors[b].played_by == "simulator"


def test_one_wrong_vendor_id_changes_nothing(agent):
    _, deal = agent
    deal_id, (a, _) = ids(deal)
    r = TestClient(app).post(f"/deals/{deal_id}/control", json={"vendor_ids": [a, str(uuid.uuid4())], "played_by": "you"})
    assert r.status_code == 404 and deal.vendors[a].played_by == "simulator"


def test_bulk_control_rejects_an_empty_list_and_bad_values(agent):
    _, deal = agent
    deal_id, (a, _) = ids(deal)
    c = TestClient(app)
    assert c.post(f"/deals/{deal_id}/control", json={"vendor_ids": [], "played_by": "you"}).status_code == 422
    assert c.post(f"/deals/{deal_id}/control", json={"vendor_ids": ["nope"], "played_by": "you"}).status_code == 422
    assert c.post(f"/deals/{deal_id}/control", json={"vendor_ids": [a], "played_by": "robot"}).status_code == 422


def test_you_can_choose_which_vendors_you_play_when_the_deal_is_created(repo):
    body = payload()
    body["vendors"][0]["played_by"] = "you"
    r = TestClient(app).post("/deals", json=body)
    vendors = repo.deals[r.json()["id"]]["vendors"]
    assert vendors[0]["played_by"] == "you" and all(v["played_by"] == "simulator" for v in vendors[1:])


def test_an_unknown_played_by_is_rejected_at_creation(repo):
    body = payload()
    body["vendors"][0]["played_by"] = "robot"
    assert TestClient(app).post("/deals", json=body).status_code == 422


def test_search_again_is_refused_when_the_deal_already_has_a_market_price(agent):
    from app.schemas.research import ResearchResult

    _, deal = agent
    deal_id, _ = ids(deal)
    deal.research = ResearchResult(currency="USD", low=1, median=2, high=3, confidence="medium", available=True)
    r = TestClient(app).post(f"/deals/{deal_id}/research/retry")
    assert r.status_code == 409 and r.json()["detail"]["error"] == "research_ok"
    assert TestClient(app).post(f"/deals/{uuid.uuid4()}/research/retry").status_code == 404


def test_search_again_is_accepted_after_a_failed_research(agent):
    from app.schemas.research import ResearchResult

    _runtime, deal = agent
    deal_id, _ = ids(deal)
    deal.research = ResearchResult(currency="USD", available=False, reason="No usable prices were found.")
    with TestClient(app) as c:
        assert c.post(f"/deals/{deal_id}/research/retry").status_code == 202
        import time

        for _ in range(60):
            if deal.research is not None and deal.research.available:
                break
            time.sleep(0.05)
    assert deal.research is not None and deal.research.available
