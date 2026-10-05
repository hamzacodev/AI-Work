import asyncio

from app.agents.manager import DealManager, ManagerDeps
from app.core.db import SupabaseDealStore
from app.negotiation.strategy import Recommendation
from app.negotiation.tactics import Tactics
from app.schemas.records import Event, Outbound
from tests.fake_supabase import FakeSupabase
from tests.test_manager import FIRST, FakeLLM, research


def seed(db: FakeSupabase, names=("Alpha", "Beta")):
    deal = db.table("deals").insert({"item": "Dell XPS 15", "max_price": 800, "currency": "USD", "must_haves": ["16GB RAM"], "address": "12 Example Street", "phone": "+92 300 1234567", "status": "created"}).execute().data[0]
    vendors = db.table("vendors").insert([{"deal_id": deal["id"], "name": n, "contact": f"{n.lower()}@shop.example.com", "channel": "email", "status": "sent"} for n in names]).execute().data
    return deal["id"], [v["id"] for v in vendors]


async def test_a_new_deal_loads_with_defaults():
    db = FakeSupabase()
    deal_id, vids = seed(db)
    deal = await SupabaseDealStore(db).get(deal_id)
    assert deal.item == "Dell XPS 15" and deal.max_price == 800 and deal.address == "12 Example Street"
    assert list(deal.vendors) == vids and deal.vendors[vids[0]].status == "negotiating"  # "sent" means negotiating
    assert deal.research is None and deal.max_rounds == 6 and deal.ceiling_ratio == 0.95


async def test_everything_the_agent_knows_survives_a_restart():
    db = FakeSupabase()
    deal_id, (a, b) = seed(db)
    store = SupabaseDealStore(db)
    deal = await store.get(deal_id)
    deal.tactics = Tactics(may_buy_quantity=2, can_decide_today=True)
    deal.research = await research()(deal)
    v = deal.vendors[a]
    v.offer, v.offers_so_far, v.last_counter, v.rounds, v.stall_count = 840.0, [880.0, 840.0], 665.0, 2, 1
    v.firm, v.firm_pushes, v.last_leverage, v.status, v.stop_reason = True, 1, 650.0, "paused", "firm_price"
    v.recommendation = Recommendation("counter", "Try once more.")
    from app.agents.fact_rules import Turn

    v.conversation += [Turn(sender="vendor", text="$880"), Turn(sender="agent", text="Could you do $651?")]
    v.events.append(Event("Researcher", "Found a fair price.", [{"title": "Retailer A", "url": "https://a.example.com"}]))
    await store.save(deal)

    again = await SupabaseDealStore(db).get(deal_id)  # a fresh store: the server restarted
    w = again.vendors[a]
    assert (w.offer, w.offers_so_far, w.last_counter, w.rounds, w.stall_count) == (840.0, [880.0, 840.0], 665.0, 2, 1)
    assert (w.firm, w.firm_pushes, w.last_leverage, w.status, w.stop_reason) == (True, 1, 650.0, "paused", "firm_price")
    assert w.recommendation == Recommendation("counter", "Try once more.")
    assert [(t.sender, t.text) for t in w.conversation] == [("vendor", "$880"), ("agent", "Could you do $651?")]
    assert w.events[0].agent == "Researcher" and w.events[0].sources[0]["title"] == "Retailer A"
    assert again.tactics.may_buy_quantity == 2 and again.tactics.can_decide_today
    assert again.research is not None and again.research.median == 700 and again.vendors[b].offer is None


async def test_only_what_changed_is_written():
    db = FakeSupabase()
    deal_id, (a, _) = seed(db)
    store = SupabaseDealStore(db)
    deal = await store.get(deal_id)
    await store.save(deal)
    db.writes.clear()
    await store.save(deal)
    assert db.writes == []  # nothing changed, nothing written
    deal.vendors[a].offer = 880.0
    await store.save(deal)
    assert db.writes == [("vendors", "update", 1)]  # one vendor row, not both


async def test_messages_are_added_once_and_stay_in_order():
    db = FakeSupabase()
    deal_id, (a, _) = seed(db)
    store = SupabaseDealStore(db)
    deal = await store.get(deal_id)
    from app.agents.fact_rules import Turn

    for i in range(4):
        deal.vendors[a].conversation.append(Turn(sender="vendor" if i % 2 == 0 else "agent", text=f"message {i}"))
        await store.save(deal)
    await store.save(deal)
    rows = [r["text"] for r in sorted(db.tables["messages"], key=lambda r: r["created_at"])]
    assert rows == ["message 0", "message 1", "message 2", "message 3"]
    assert len((await SupabaseDealStore(db).get(deal_id)).vendors[a].conversation) == 4


async def test_two_vendors_saving_at_once_do_not_overwrite_each_other():
    db = FakeSupabase()
    deal_id, (a, b) = seed(db)
    store = SupabaseDealStore(db)
    deal = await store.get(deal_id)

    async def work(vid, price):
        deal.vendors[vid].offer = price
        await store.save(deal)

    await asyncio.gather(work(a, 880.0), work(b, 900.0))
    again = await SupabaseDealStore(db).get(deal_id)
    assert again.vendors[a].offer == 880 and again.vendors[b].offer == 900


async def test_a_failed_write_is_retried_by_the_next_save():
    db = FakeSupabase()
    deal_id, (a, _) = seed(db)
    store = SupabaseDealStore(db)
    deal = await store.get(deal_id)
    deal.vendors[a].offer = 880.0
    db.fail_next_write = True
    try:
        await store.save(deal)
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    await store.save(deal)  # nothing was lost: the same change is written now
    assert (await SupabaseDealStore(db).get(deal_id)).vendors[a].offer == 880


async def test_a_missing_deal_is_an_error():
    import pytest

    with pytest.raises(KeyError):
        await SupabaseDealStore(FakeSupabase()).get("nope")


async def test_the_maximum_price_is_only_in_the_deal_row_never_in_messages_or_events():
    db = FakeSupabase()
    deal_id, vids = seed(db, ("Alpha",))
    store = SupabaseDealStore(db)
    sent: list[Outbound] = []

    async def on_send(o):
        sent.append(o)

    mgr = DealManager(ManagerDeps(llm=FakeLLM(), store=store, research=research(), on_send=on_send))
    await mgr.start(deal_id)
    await mgr.on_vendor_message(deal_id, vids[0], "$880 ready to ship")
    texts = [r["text"] for r in db.tables["messages"]] + [r["text"] for r in db.tables["events"]]
    assert texts and not any("$800" in t for t in texts)


async def test_a_negotiation_can_stop_in_the_middle_and_carry_on_after_a_restart():
    db = FakeSupabase()
    deal_id, (a, b) = seed(db)
    first = DealManager(ManagerDeps(llm=FakeLLM(), store=SupabaseDealStore(db), research=research()))
    await first.start(deal_id)
    await first.on_vendor_message(deal_id, a, "$880 ready to ship")
    await first.on_vendor_message(deal_id, b, "$640 and that is good.")

    sent: list[Outbound] = []

    async def on_send(o):
        sent.append(o)

    # the server restarts: a brand new store and manager that only know the database
    second = DealManager(ManagerDeps(llm=FakeLLM(), store=SupabaseDealStore(db), research=research(), on_send=on_send))
    deal = await second.deps.store.get(deal_id)
    assert deal.vendors[a].rounds == 1 and deal.vendors[a].last_counter == 651 and deal.research is not None
    assert [t.sender for t in deal.vendors[a].conversation][:2] == ["agent", "vendor"]
    await second.on_vendor_message(deal_id, a, "OK, $700.")
    # Beta's $640 was saved before the restart. Our saved counter ($651) is above it, so the agent asks Alpha to beat $640.
    assert sent and sent[0].action == "leverage" and sent[0].leverage_price == 640
    summary = await second.summary(deal_id)
    assert summary.best.name == "Beta"
    assert FIRST in [t.text for t in deal.vendors[a].conversation]
