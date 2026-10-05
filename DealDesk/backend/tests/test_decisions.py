import uuid

import pytest
from fastapi.testclient import TestClient

from app.agents import closer
from app.agents.fact_rules import Turn
from app.agents.manager import ManagerDeps
from app.agents.runtime import build_runtime
from app.api.deals import get_agent_runtime
from app.core import resume
from app.guardrails.limit_checker import Context, check_outgoing
from app.schemas.records import DealRecord, InMemoryDealStore, VendorRecord
from main import app
from tests.test_manager import FakeLLM, research

ADDRESS = "12 Example Street, Karachi"
PHONE = "+92 300 1234567"


def make(offers=(620.0, 650.0, 840.0), played_by="you"):
    store = InMemoryDealStore()
    deal = DealRecord(id=str(uuid.uuid4()), item="Dell XPS 15", max_price=800.0, must_haves=["16GB RAM"], address=ADDRESS, phone=PHONE)
    for n, price in zip(("Gamma", "Beta", "Alpha"), offers, strict=False):
        vid = str(uuid.uuid4())
        v = VendorRecord(vid, n, f"{n.lower()}@shop.example.com", offer=price, offers_so_far=[price], played_by=played_by, status="paused")
        v.conversation += [Turn(sender="agent", text="Hello, what is your best price?"), Turn(sender="vendor", text=f"${price:g}")]
        deal.vendors[vid] = v
    store.add(deal)
    runtime = build_runtime(store, lambda rt: ManagerDeps(llm=FakeLLM(), store=store, research=research(), on_send=rt.on_send))
    return runtime, store, deal


def vid(deal, name):
    return next(k for k, v in deal.vendors.items() if v.name == name)


async def settle():
    while resume._tasks:
        await resume.wait_for_tasks()


# ---------------------------------------------------------------- accept


async def test_accepting_sends_the_confirmation_only_to_the_chosen_vendor_and_closes_the_rest():
    rt, _, deal = make()
    g = vid(deal, "Gamma")
    await rt.decide(deal.id, g, "accept")
    gamma = deal.vendors[g]
    msg = gamma.conversation[-1].text
    assert gamma.conversation[-1].sender == "agent" and "$620" in msg and "cash on delivery" in msg.lower()
    assert ADDRESS in msg and PHONE in msg
    assert gamma.status == "closed" and gamma.stop_reason == "accepted"
    assert deal.status == "accepted" and deal.accepted_vendor_id == g and deal.accepted_price == 620
    for name in ("Beta", "Alpha"):
        v = deal.vendors[vid(deal, name)]
        assert v.status == "closed" and v.stop_reason == "other_vendor_accepted"
        assert not any(ADDRESS in t.text or PHONE in t.text for t in v.conversation)  # they never see your address or phone
        assert v.conversation[-1].sender == "vendor"  # nothing was sent to them


async def test_the_confirmation_message_passes_the_real_limit_checker_in_the_closing_phase():
    _, _, deal = make()
    g = deal.vendors[vid(deal, "Gamma")]
    text = closer.closing_message(deal, g, 620.0)
    ctx = {
        "max_price": 800.0, "recipient": g.contact, "vendor_contacts": frozenset(v.contact for v in deal.vendors.values()),
        "vendor_offer": 620.0, "vendor_prices": (620.0,), "address": ADDRESS, "phone": PHONE,
    }  # fmt: skip
    assert check_outgoing(text, Context(**ctx, phase="closing", accepted_contact=g.contact)).allowed
    assert not check_outgoing(text, Context(**ctx, phase="negotiating")).allowed  # the same text is blocked before you accept


async def test_the_confirmation_never_contains_the_maximum_price():
    rt, _, deal = make()
    await rt.decide(deal.id, vid(deal, "Gamma"), "accept")
    assert "800" not in deal.vendors[vid(deal, "Gamma")].conversation[-1].text


async def test_accepting_above_the_maximum_needs_a_confirmation():
    rt, _, deal = make(offers=(840.0, 900.0, 950.0))
    a = vid(deal, "Gamma")
    with pytest.raises(closer.NeedsConfirmation):
        await rt.decide(deal.id, a, "accept")
    assert deal.status == "negotiating" and deal.vendors[a].status == "paused"  # nothing happened
    await rt.decide(deal.id, a, "accept", confirm_over_limit=True)
    assert deal.status == "accepted"


async def test_you_cannot_accept_twice_or_accept_a_closed_or_blocked_vendor():
    rt, _, deal = make()
    await rt.decide(deal.id, vid(deal, "Gamma"), "accept")
    with pytest.raises(closer.DecisionError) as e:
        await rt.decide(deal.id, vid(deal, "Beta"), "accept")
    assert e.value.code == "already_accepted"
    rt2, _, deal2 = make()
    deal2.vendors[vid(deal2, "Beta")].status = "blocked"
    with pytest.raises(closer.DecisionError) as e:
        await rt2.decide(deal2.id, vid(deal2, "Beta"), "accept")
    assert e.value.code == "vendor_blocked"


async def test_you_cannot_accept_a_vendor_without_a_price():
    rt, _, deal = make()
    v = deal.vendors[vid(deal, "Gamma")]
    v.offer = None
    with pytest.raises(closer.DecisionError) as e:
        await rt.decide(deal.id, v.vendor_id, "accept")
    assert e.value.code == "no_offer"


async def test_the_ai_can_never_accept():
    _, store, deal = make()
    with pytest.raises(closer.DecisionError) as e:
        await closer.accept(store, deal.id, vid(deal, "Gamma"), actor="ai")
    assert e.value.status == 403 and deal.status == "negotiating"


async def test_an_unsafe_closing_message_accepts_nothing(monkeypatch):
    rt, _, deal = make()
    monkeypatch.setattr(closer, "closing_message", lambda d, v, p: "Pay by bitcoin and send an advance. " + d.address)
    with pytest.raises(closer.DecisionError) as e:
        await rt.decide(deal.id, vid(deal, "Gamma"), "accept")
    assert e.value.code == "closing_blocked" and deal.status == "negotiating" and deal.vendors[vid(deal, "Gamma")].status == "paused"


async def test_unknown_deal_and_vendor_are_404():
    rt, _, deal = make()
    with pytest.raises(closer.DecisionError) as e:
        await rt.decide(deal.id, str(uuid.uuid4()), "accept")
    assert e.value.status == 404
    with pytest.raises(closer.DecisionError) as e:
        await rt.decide(str(uuid.uuid4()), "x", "accept")
    assert e.value.status == 404


async def test_after_accepting_no_vendor_message_is_processed():
    rt, _, deal = make()
    await rt.decide(deal.id, vid(deal, "Gamma"), "accept")
    n = len(deal.vendors[vid(deal, "Beta")].conversation)
    state = await rt.manager.on_vendor_message(deal.id, vid(deal, "Beta"), "OK $500!")
    assert state["outcome"] == "ignored" and deal.vendors[vid(deal, "Beta")].conversation[-1].text == "OK $500!"
    assert deal.vendors[vid(deal, "Beta")].conversation[n - 1].sender == "vendor" and deal.status == "accepted"


# ---------------------------------------------------------------- counter and reject


async def test_your_counter_is_sent_as_you_and_the_fake_vendor_answers_it():
    rt, _, deal = make(played_by="simulator")
    b = vid(deal, "Beta")
    deal.vendors[b].persona = "friendly"
    await rt.decide(deal.id, b, "counter", 600.0)
    v = deal.vendors[b]
    assert v.conversation[-2:] == [Turn(sender="owner", text="Could you do $600?")] or v.conversation[-1].text == "Could you do $600?"
    assert v.last_counter == 600 and v.rounds == 1 and v.status == "negotiating"
    await settle()
    assert any(t.sender == "vendor" and t.simulated for t in v.conversation[-3:])


async def test_a_counter_above_the_ceiling_needs_a_confirmation_and_one_above_the_maximum_is_blocked():
    rt, _, deal = make(offers=(900.0, 900.0, 900.0))
    g = vid(deal, "Gamma")
    with pytest.raises(closer.NeedsConfirmation):
        await rt.decide(deal.id, g, "counter", 780.0)  # above the ceiling (760), below the maximum
    await rt.decide(deal.id, g, "counter", 780.0, confirm_over_limit=True)
    assert deal.vendors[g].last_counter == 780
    b = vid(deal, "Beta")
    with pytest.raises(closer.DecisionError) as e:
        await rt.decide(deal.id, b, "counter", 800.0, confirm_over_limit=True)  # exactly the maximum: would give it away
    assert e.value.code == "counter_at_maximum"


async def test_a_counter_must_be_positive_and_below_the_vendors_price():
    rt, _, deal = make()
    g = vid(deal, "Gamma")
    for bad in (None, 0, -5):
        with pytest.raises(closer.DecisionError):
            await rt.decide(deal.id, g, "counter", bad)
    with pytest.raises(closer.DecisionError) as e:
        await rt.decide(deal.id, g, "counter", 700.0)  # Gamma asks 620
    assert e.value.code == "counter_not_below_offer"


async def test_rejecting_closes_only_that_vendor_and_sends_nothing():
    rt, _, deal = make()
    a = vid(deal, "Alpha")
    n = len(deal.vendors[a].conversation)
    await rt.decide(deal.id, a, "reject")
    assert deal.vendors[a].status == "closed" and deal.vendors[a].stop_reason == "rejected_by_user"
    assert len(deal.vendors[a].conversation) == n and deal.status == "negotiating"
    assert deal.vendors[vid(deal, "Gamma")].status == "paused"


# ---------------------------------------------------------------- finish: stop and choose, reject all


async def test_stop_and_choose_pauses_the_vendors_still_negotiating():
    rt, _, deal = make()
    deal.vendors[vid(deal, "Alpha")].status = "negotiating"
    await rt.finish(deal.id, "stop_and_choose")
    a = deal.vendors[vid(deal, "Alpha")]
    assert a.status == "paused" and a.stop_reason == "stopped_by_user" and deal.status == "negotiating"


async def test_reject_all_closes_every_vendor_and_ends_the_deal():
    rt, _, deal = make()
    n = sum(len(v.conversation) for v in deal.vendors.values())
    await rt.finish(deal.id, "reject_all")
    assert deal.status == "rejected" and all(v.status == "closed" for v in deal.vendors.values())
    assert sum(len(v.conversation) for v in deal.vendors.values()) == n  # nothing was sent
    with pytest.raises(closer.DecisionError):
        await rt.finish(str(uuid.uuid4()), "reject_all")


async def test_rejecting_the_last_open_vendor_ends_the_deal():
    rt, _, deal = make()
    for name in ("Gamma", "Beta", "Alpha"):
        await rt.decide(deal.id, vid(deal, name), "reject")
    assert deal.status == "rejected"


# ---------------------------------------------------------------- the HTTP side


@pytest.fixture
def client():
    rt, _, deal = make()
    app.dependency_overrides[get_agent_runtime] = lambda: rt
    yield TestClient(app), deal
    app.dependency_overrides.clear()


def test_http_accept_ok(client):
    c, deal = client
    r = c.post(f"/deals/{deal.id}/decision", json={"vendor_id": vid(deal, "Gamma"), "action": "accept"})
    assert r.status_code == 200 and r.json() == {"status": "ok"} and deal.status == "accepted"


def test_http_over_limit_returns_the_contract_body(client):
    c, deal = client
    deal.vendors[vid(deal, "Gamma")].offer = 900.0
    r = c.post(f"/deals/{deal.id}/decision", json={"vendor_id": vid(deal, "Gamma"), "action": "accept"})
    assert r.status_code == 409 and r.json()["error"] == "over_limit" and r.json()["requires_confirmation"] is True and r.json()["message"]
    r = c.post(f"/deals/{deal.id}/decision", json={"vendor_id": vid(deal, "Gamma"), "action": "accept", "confirm_over_limit": True})
    assert r.status_code == 200


def test_http_errors_use_a_readable_body(client):
    c, deal = client
    r = c.post(f"/deals/{deal.id}/decision", json={"vendor_id": str(uuid.uuid4()), "action": "accept"})
    assert r.status_code == 404 and r.json()["error"] == "vendor_not_found"
    assert c.post(f"/deals/{deal.id}/decision", json={"vendor_id": "nope", "action": "accept"}).status_code == 422
    assert c.post(f"/deals/{deal.id}/decision", json={"vendor_id": vid(deal, "Gamma"), "action": "buy"}).status_code == 422
    assert c.post(f"/deals/{deal.id}/decision", json={"vendor_id": vid(deal, "Gamma"), "action": "counter", "counter_price": -1}).status_code == 422


def test_http_finish(client):
    c, deal = client
    assert c.post(f"/deals/{deal.id}/finish", json={"action": "reject_all"}).json() == {"status": "ok"}
    assert deal.status == "rejected"
    assert c.post(f"/deals/{deal.id}/finish", json={"action": "explode"}).status_code == 422


def test_http_decisions_say_so_when_the_agent_is_off():
    app.dependency_overrides.clear()
    r = TestClient(app).post(f"/deals/{uuid.uuid4()}/decision", json={"vendor_id": str(uuid.uuid4()), "action": "accept"})
    assert r.status_code == 503


async def test_a_hand_counter_above_your_maximum_needs_a_confirmation_and_then_goes_through():
    # Your right as the buyer, e.g. maximum 800 and the cheapest vendor says 840: you may try 805 after confirming.
    rt, _, deal = make(offers=(900.0, 900.0, 900.0))
    g = vid(deal, "Gamma")
    with pytest.raises(closer.NeedsConfirmation) as e:
        await rt.decide(deal.id, g, "counter", 805.0)
    assert "above your maximum" in str(e.value)
    await rt.decide(deal.id, g, "counter", 805.0, confirm_over_limit=True)
    assert deal.vendors[g].last_counter == 805 and deal.vendors[g].conversation[-1].text == "Could you do $805?"


async def test_a_hand_counter_of_exactly_your_maximum_is_always_refused_with_a_plain_reason():
    rt, _, deal = make()
    g = vid(deal, "Alpha")
    for confirm in (False, True):
        with pytest.raises(closer.DecisionError) as e:
            await rt.decide(deal.id, g, "counter", 800.0, confirm)
        assert e.value.code == "counter_at_maximum" and "exactly your maximum" in str(e.value)
