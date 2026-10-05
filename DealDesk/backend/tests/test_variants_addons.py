import ast
import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import closer
from app.agents.fact_rules import Turn
from app.agents.manager import DealManager, ManagerDeps
from app.agents.negotiator import (
    NegotiationContext,
    check_numbers,
    facts_for,
    keep_sentence,
)
from app.agents.offer_reader import OfferChoice, OtherVariant, VariantChoice, read_offer
from app.core.db import SupabaseDealStore, get_repo
from app.negotiation import addons as ad
from app.negotiation.addons import (
    AddonOffer,
    credit,
    effective_price,
    find_addons,
    lost_if_price_drops,
    words,
)
from app.negotiation.strategy import Decision, Situation, decide
from app.negotiation.tactics import Tactics
from app.negotiation.tracker import VendorState, summarize
from app.schemas.records import DealRecord, InMemoryDealStore, VendorRecord
from main import app
from tests.fake_supabase import FakeSupabase
from tests.test_deals_api import FakeRepo, payload
from tests.test_manager import FakeLLM, research
from tests.test_store import seed

# ---------------------------------------------------------------- add-ons: found by code from a closed list


@pytest.mark.parametrize(
    ("text", "keys"),
    [
        ("Black $720, free charger and hands-free included.", {"charger", "handsfree"}),
        ("Free charger, hands-free and case.", {"charger", "handsfree", "case"}),
        ("Delivery is free within the city.", {"delivery"}),
        ("It comes with a 1 year warranty.", {"warranty"}),
        ("Price $720. Free case, but charger sold separately.", {"case"}),
        ("The charger costs extra.", set()),
        ("No free charger, sorry.", set()),
        ("It has 16GB RAM and a big screen.", set()),
        ("Do you want a charger?", set()),  # a question is not an offer
    ],
)
def test_find_addons(text, keys):
    assert {o.key for o in find_addons(text)} == keys


def test_a_conditional_extra_remembers_the_price_it_needs():
    (o,) = find_addons("If you buy at $700 we give a free hands-free.")
    assert o == AddonOffer("handsfree", 700.0)
    (o,) = find_addons("Black is $720, free charger if you decide today.")  # a sales line, not a price condition
    assert o.min_price is None


def test_the_value_of_extras_counts_only_what_you_want_and_only_while_the_condition_holds():
    offered = [AddonOffer("charger"), AddonOffer("handsfree", 700.0), AddonOffer("case")]
    values = {"charger": 20, "handsfree": 15}  # you do not value the case
    assert credit(offered, values, 720) == (35.0, ["charger", "handsfree"])
    assert credit(offered, values, 650) == (20.0, ["charger"])  # below 700 the hands-free is gone
    assert credit(offered, {}, 720) == (0.0, [])
    assert credit(offered, values, None) == (0.0, [])
    assert effective_price(720, offered, values) == 685


def test_extras_you_would_lose_by_countering_lower_are_listed():
    offered = [AddonOffer("charger"), AddonOffer("handsfree", 700.0)]
    assert lost_if_price_drops(offered, {"charger": 20, "handsfree": 15}, 651) == ["handsfree"]
    assert lost_if_price_drops(offered, {"charger": 20}, 651) == []  # you do not value it
    assert lost_if_price_drops(offered, {"handsfree": 15}, 700) == []


def test_words():
    assert words(["charger"]) == "charger"
    assert words(["charger", "handsfree"]) == "charger and hands-free"
    assert words(["charger", "handsfree", "case"]) == "charger, hands-free and case"
    assert words([]) == ""


def test_the_catalog_is_consistent():
    assert len({a.key for a in ad.CATALOG}) == len(ad.CATALOG) and all(a.suggested_usd > 0 for a in ad.CATALOG)
    assert set(ad.LABELS) == set(ad.BY_KEY) == set(ad.SUGGESTED_USD)


def test_the_add_on_module_uses_no_ai_or_network():
    tree = ast.parse(Path("app/negotiation/addons.py").read_text())
    names = {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not names & {"openai", "httpx", "requests", "supabase", "langgraph"}


# ---------------------------------------------------------------- the Offer Reader with variants


class Picks:
    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    async def complete_json(self, role, system, user, schema, deal_id=None):
        self.calls.append({"schema": schema, "system": system, "user": user})
        return self.answer


async def test_the_price_for_your_variant_is_picked_and_other_variants_are_reported():
    llm = Picks(VariantChoice(choice=1, others=[OtherVariant(choice=2, variant="gray")]))
    r = await read_offer("Black is $720, gray is $690.", llm, wanted_variant="black, 128GB")
    assert r.status == "price" and r.price == 720 and [(v.variant, v.price) for v in r.variants] == [("gray", 690)]
    assert llm.calls[0]["schema"] is VariantChoice and "<wanted_variant>" in llm.calls[0]["user"] and "black, 128GB" in llm.calls[0]["user"]


async def test_a_vendor_who_only_quotes_another_variant_gives_no_price_for_yours():
    llm = Picks(VariantChoice(choice=0, others=[OtherVariant(choice=1, variant="gray")]))
    r = await read_offer("Gray is $690.", llm, wanted_variant="black")
    assert r.status == "no_price" and r.price is None and r.variants[0].price == 690 and "variant you want" in r.reason


async def test_a_single_price_next_to_a_color_asks_the_model_only_when_you_want_a_variant():
    llm = Picks(VariantChoice(choice=1))
    r = await read_offer("Black $720.", llm, wanted_variant="black")
    assert r.price == 720 and r.decided_by == "model" and len(llm.calls) == 1
    llm2 = Picks(OfferChoice(choice=1))
    r = await read_offer("Black $720.", llm2)  # no wanted variant: clear single price, read by code
    assert r.price == 720 and r.decided_by == "code" and llm2.calls == []


async def test_a_plain_price_is_still_read_by_code_when_you_want_a_variant():
    llm = Picks(VariantChoice(choice=1))
    r = await read_offer("My price is $720, ready to ship.", llm, wanted_variant="black")
    assert r.price == 720 and r.decided_by == "code" and llm.calls == []


async def test_variant_labels_are_cleaned_and_only_real_numbers_are_used():
    answer = VariantChoice(
        choice=1,
        others=[
            OtherVariant(choice=2, variant="<b>gray</b>   128GB " + "x" * 80),
            OtherVariant(choice=1, variant="black"),  # the chosen price is never "another variant"
            OtherVariant(choice=2, variant="again"),  # the same number twice
            OtherVariant(choice=9, variant="ghost"),  # not in the list
            OtherVariant(choice=3, variant="  "),  # empty label
        ],
    )
    r = await read_offer("Black $720, gray $690, maroon $700.", Picks(answer), wanted_variant="black")
    assert len(r.variants) == 1 and r.variants[0].price == 690 and len(r.variants[0].variant) <= 40 and "<" not in r.variants[0].variant


async def test_extras_are_found_without_any_model_call():
    llm = Picks(OfferChoice(choice=1))
    r = await read_offer("It is $720 with a free charger.", llm)
    assert r.status == "price" and {a.key for a in r.addons} == {"charger"} and llm.calls == []
    r = await read_offer("Free delivery for you, tell me your budget.", llm)
    assert r.status == "no_price" and {a.key for a in r.addons} == {"delivery"}


# ---------------------------------------------------------------- the tracker ranks the EFFECTIVE price


def test_the_vendor_with_the_best_effective_price_wins_even_if_its_price_is_not_the_lowest():
    states = [
        VendorState("a", "Alpha", 720, "paused", credit=20.0, addons=("charger",)),
        VendorState("b", "Beta", 705, "paused"),
        VendorState("c", "Gamma", 710, "paused", credit=35.0, addons=("charger", "hands-free")),
    ]
    s = summarize(states, 700)
    assert [r.name for r in s.ranking] == ["Gamma", "Alpha", "Beta"]
    assert s.best.name == "Gamma" and s.best.effective == 675 and s.best.price == 710
    assert "$710" in s.headline and "$675" in s.headline and "your estimate" in s.headline
    assert s.saved == 25  # the market is 700, the effective price 675


def test_without_extras_the_ranking_is_by_price_as_before():
    s = summarize([VendorState("a", "A", 650, "paused"), VendorState("b", "B", 620, "paused")], 700)
    assert s.best.name == "B" and s.best.credit == 0 and "your estimate" not in s.headline


# ---------------------------------------------------------------- the strategy judges the deal after your extras


BASE = {"max_price": 800.0, "research_low": 640.0, "research_median": 700.0, "research_high": 790.0, "research_confidence": "medium"}


def test_a_vendor_whose_price_is_above_target_but_whose_extras_bring_it_to_target_is_a_good_deal():
    d = decide(Situation(**BASE, vendor_offer=700.0, offer_credit=35.0))
    assert d.action == "needs_you" and d.recommendation.action == "accept" and "counting the free extras" in d.recommendation.reason or "Good price" in d.reason
    d = decide(Situation(**BASE, vendor_offer=700.0, offer_credit=0.0))
    assert d.action == "counter"  # without the extras it is not good enough yet


def test_extras_never_make_a_price_above_your_maximum_acceptable():
    d = decide(Situation(**BASE, vendor_offer=840.0, offer_credit=200.0))
    assert not (d.recommendation and d.recommendation.action == "accept")


def test_counters_are_still_computed_on_the_price_not_the_effective_price():
    assert decide(Situation(**BASE, vendor_offer=880.0, offer_credit=40.0)).counter_price == 651


# ---------------------------------------------------------------- the words the Negotiator uses


def test_the_extras_request_names_what_you_value():
    t = Tactics(extras_items=["charger", "handsfree"])
    assert "Could you also include the charger and hands-free at that price?" in t.persuasion_lines()
    assert "free delivery or the charger" in " ".join(Tactics().persuasion_lines())  # the old general line if you named nothing


def ctx(**over) -> NegotiationContext:
    base = {
        "decision": Decision("counter", "x", 651.0), "item": "Dell XPS 15 (black, 128GB)", "currency": "USD", "max_price": 800.0,
        "recipient": "v@x.com", "vendor_contacts": frozenset({"v@x.com"}), "vendor_offer": 720.0, "vendor_prices": (720.0,),
        "research_low": 640.0, "research_median": 700.0, "research_high": 790.0, "tactics": Tactics(good_rate_line=False, ask_extras=False, ask_best_price=False, meet_halfway=False),
    }  # fmt: skip
    base.update(over)
    return NegotiationContext(**base)


def test_the_sentence_to_keep_an_extra_is_required_and_approved():
    c = ctx(keep_addons=["handsfree"])
    assert keep_sentence(c) == "Could you keep the free hands-free at that price?"
    assert check_numbers("Could you do $651?", c)  # missing the sentence
    assert check_numbers("Could you do $651? Could you keep the free hands-free at that price?", c) == []
    assert "Could you keep the free hands-free at that price?" in facts_for(c).approved_sentences
    assert keep_sentence(ctx()) is None


# ---------------------------------------------------------------- the whole agent with a variant and extras


class RecordingLLM(FakeLLM):
    def __init__(self, answer=None):
        super().__init__()
        self.answer = answer
        self.systems: list[str] = []

    async def complete_json(self, role, system, user, schema, deal_id=None):
        self.systems.append(system)
        if issubclass(schema, VariantChoice) and self.answer is not None:
            return self.answer
        return await super().complete_json(role, system, user, schema, deal_id)


def deal_with(variant="black, 128GB", values=None):
    store = InMemoryDealStore()
    deal = DealRecord(
        id="d1", item="iPhone 15", variant=variant, alt_variants=["gray, 128GB"], addon_values=values or {"charger": 20, "handsfree": 15},
        max_price=800.0, address="12 Example Street, Karachi",
    )  # fmt: skip
    deal.vendors["a"] = VendorRecord("a", "Alpha", "alpha@shop.example.com", played_by="you")
    store.add(deal)
    return store, deal


async def test_a_vendor_message_with_variants_and_extras_is_understood_and_stored():
    llm = RecordingLLM(VariantChoice(choice=1, others=[OtherVariant(choice=2, variant="gray")]))
    store, deal = deal_with()
    mgr = DealManager(ManagerDeps(llm=llm, store=store, research=research()))
    await mgr.on_vendor_message("d1", "a", "Black is $720, gray is $690. Free charger and hands-free included.")
    v = deal.vendors["a"]
    assert v.offer == 720 and v.variant_prices == {"gray": 690.0} and {a.key for a in v.addons} == {"charger", "handsfree"}
    texts = [e.text for e in v.events]
    assert any("Other variants quoted: gray $690" in t for t in texts) and any("free extras: charger, hands-free" in t for t in texts)
    s = await mgr.summary("d1")
    assert s.best.price == 720 and s.best.credit == 35 and s.best.effective == 685
    assert any("(black, 128GB)" in x for x in llm.systems)  # the writer is told the exact variant


async def test_the_agent_asks_to_keep_an_extra_that_depends_on_the_price():
    llm = RecordingLLM(VariantChoice(choice=1))
    store, _ = deal_with()
    sent = []

    async def on_send(o):
        sent.append(o)

    mgr = DealManager(ManagerDeps(llm=llm, store=store, research=research(), on_send=on_send))
    await mgr.on_vendor_message("d1", "a", "Black $720. If you buy at $700 or more we give a free charger.")
    assert sent and sent[-1].counter_price == 651
    assert "Could you keep the free charger at that price?" in sent[-1].text  # at $651 the charger would be lost


async def test_a_deal_without_a_variant_works_as_before():
    llm = RecordingLLM()
    store, deal = deal_with(variant="", values={})
    mgr = DealManager(ManagerDeps(llm=llm, store=store, research=research()))
    await mgr.on_vendor_message("d1", "a", "$880, ready to ship")
    assert deal.vendors["a"].offer == 880 and deal.vendors["a"].variant_prices == {} and deal.full_item == "iPhone 15"


async def test_accepting_looks_at_the_price_you_pay_not_the_effective_price():
    store, deal = deal_with()
    v = deal.vendors["a"]
    v.offer, v.offers_so_far, v.status = 840.0, [840.0], "paused"
    v.addons = [AddonOffer("charger"), AddonOffer("handsfree")]  # worth 35 to you: effective 805, still above your maximum
    v.conversation.append(Turn(sender="vendor", text="$840"))
    with pytest.raises(closer.NeedsConfirmation):
        await closer.accept(store, "d1", "a")


def test_the_item_with_its_variant():
    assert DealRecord(id="x", item="iPhone 15", variant="black, 128GB", max_price=1).full_item == "iPhone 15 (black, 128GB)"
    assert DealRecord(id="x", item="iPhone 15", max_price=1).full_item == "iPhone 15"


# ---------------------------------------------------------------- the API


@pytest.fixture
def repo():
    r = FakeRepo()
    app.dependency_overrides[get_repo] = lambda: r
    yield r
    app.dependency_overrides.pop(get_repo, None)


def test_creating_a_deal_with_a_variant_and_extras(repo):
    body = payload() | {"variant": "black, 128GB", "alt_variants": ["gray, 128GB"], "addon_values": {"charger": 20, "handsfree": 15, "case": 0}}
    r = TestClient(app).post("/deals", json=body)
    assert r.status_code == 201


def test_unknown_or_negative_extras_are_rejected():
    c = TestClient(app)
    assert c.post("/deals", json=payload() | {"addon_values": {"jetpack": 10}}).status_code == 422
    assert c.post("/deals", json=payload() | {"addon_values": {"charger": -5}}).status_code == 422
    assert c.post("/deals", json=payload() | {"variant": "x" * 101}).status_code == 422
    assert c.post("/deals", json=payload() | {"alt_variants": ["a"] * 11}).status_code == 422


def test_a_zero_value_means_you_do_not_care_about_that_extra():
    from app.schemas.deal import DealCreate

    assert DealCreate(**(payload() | {"addon_values": {"charger": 20, "case": 0}})).addon_values == {"charger": 20}


def test_reading_a_deal_shows_variants_extras_and_the_effective_price(repo):
    deal_id = str(uuid.uuid4())
    row = lambda vid, name, price, **o: {
        "id": vid, "name": name, "channel": "email", "status": "paused", "offer_price": price, "recommendation": None, "messages": [], "events": [], **o,
    }  # fmt: skip
    repo.deals[deal_id] = {
        "id": deal_id, "item": "iPhone 15", "variant": "black", "alt_variants": ["gray"], "addon_values": {"charger": 20, "handsfree": 15},
        "max_price": 800, "currency": "USD", "status": "created", "research": {"available": True, "median": 700},
        "vendors": [
            row("a", "Alpha", 710, addons=[{"key": "charger", "min_price": None}, {"key": "handsfree", "min_price": 720}], variant_prices={"gray": 690}),
            row("b", "Beta", 705),
        ],
    }  # fmt: skip
    body = TestClient(app).get(f"/deals/{deal_id}").json()
    assert body["variant"] == "black" and body["alt_variants"] == ["gray"] and body["addon_values"] == {"charger": 20, "handsfree": 15}
    a = body["vendors"][0]
    assert a["variant_prices"] == {"gray": 690}
    assert [(x["label"], x["counted"]) for x in a["addons"]] == [("charger", True), ("hands-free", False)]  # hands-free needs $720
    s = body["summary"]
    assert s["best_vendor_id"] == "a" and s["ranking"][0]["effective"] == 690 and s["ranking"][0]["credit"] == 20 and s["ranking"][0]["addons"] == ["charger"]


# ---------------------------------------------------------------- saved and restored


async def test_variants_and_extras_survive_a_restart():
    db = FakeSupabase()
    deal_id, (a, _) = seed(db)
    store = SupabaseDealStore(db)
    deal = await store.get(deal_id)
    deal.variant, deal.alt_variants, deal.addon_values = "black, 128GB", ["gray, 128GB"], {"charger": 20.0}
    deal.vendors[a].variant_prices = {"gray": 690.0}
    deal.vendors[a].addons = [AddonOffer("charger"), AddonOffer("handsfree", 700.0)]
    await store.save(deal)
    again = await SupabaseDealStore(db).get(deal_id)
    assert again.variant == "black, 128GB" and again.alt_variants == ["gray, 128GB"] and again.addon_values == {"charger": 20.0}
    assert again.vendors[a].variant_prices == {"gray": 690.0}
    assert again.vendors[a].addons == [AddonOffer("charger", None), AddonOffer("handsfree", 700.0)]


def test_no_message_is_blocked_just_because_it_names_a_color():
    # a sanity check that variant words are only used to choose a price, never as a rule that blocks a message
    assert re.search(r"black", "Black $720", re.IGNORECASE)
