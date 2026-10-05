import random
from itertools import pairwise

import pytest

from app.agents.safety_rules import scan, strongest
from app.core.llm import LLMError
from app.guardrails.prices import extract_prices
from app.simulator.personas import ATTACKS, PERSONAS
from app.simulator.vendor_sim import (
    Sentence,
    VendorSim,
    format_price,
    reply_delay,
    round_price,
)

MEDIAN = 700.0
NAMES = list(PERSONAS)


async def play(name: str, counters: list[float | None], seed: int = 1, **kw):
    sim = VendorSim(name, MEDIAN, item="Dell XPS 15", seed=seed, **kw)
    turns = [await sim.opening()]
    for c in counters:
        turns.append(await sim.reply(c))
    return sim, turns


# ---------------------------------------------------------------- the personas

def test_six_personas_with_sane_numbers():
    assert set(PERSONAS) == {"friendly", "pushy", "liar", "attacker", "stubborn", "chatty"}
    for key, p in PERSONAS.items():
        assert p.name == key
        assert 0 < p.concession_rate <= 1
        assert p.opening_markup >= 0 and p.floor_ratio > 0 and p.traits


@pytest.mark.parametrize("name", NAMES)
async def test_opening_price_and_floor_come_from_the_persona_numbers(name):
    p = PERSONAS[name]
    sim = VendorSim(name, MEDIAN, seed=3)
    assert sim.opening_price == round_price(MEDIAN * (1 + p.opening_markup))
    assert sim.floor == round_price(MEDIAN * p.floor_ratio)
    first = await sim.opening()
    assert first.price == sim.opening_price


async def test_friendly_opens_near_the_market_and_pushy_far_above_it():
    friendly = VendorSim("friendly", MEDIAN).opening_price
    pushy = VendorSim("pushy", MEDIAN).opening_price
    assert friendly <= MEDIAN * 1.06
    assert pushy >= MEDIAN * 1.25


# ---------------------------------------------------------------- price rules (code, not the model)

@pytest.mark.parametrize("name", NAMES)
async def test_price_never_goes_below_the_floor_or_up(name):
    rng = random.Random(7)
    counters = [round(rng.uniform(100, 1200)) for _ in range(40)]
    sim, turns = await play(name, counters)
    prices = [t.price for t in turns]
    assert all(p >= sim.floor for p in prices), (name, min(prices), sim.floor)
    assert all(b <= a for a, b in pairwise(prices)), "the vendor never raises the price"


@pytest.mark.parametrize("name", NAMES)
async def test_lowball_buyer_never_pushes_the_vendor_under_the_floor(name):
    sim, turns = await play(name, [1.0] * 50)
    assert turns[-1].price >= sim.floor and not any(t.agreed for t in turns)


@pytest.mark.parametrize("name", NAMES)
async def test_vendor_takes_a_counter_at_or_above_what_it_would_give(name):
    sim = VendorSim(name, MEDIAN, seed=2)
    await sim.opening()
    t = await sim.reply(sim.opening_price)  # the buyer offers the full asking price
    assert t.agreed and t.price == sim.opening_price


async def test_a_counter_below_the_floor_is_never_taken():
    sim = VendorSim("friendly", MEDIAN)
    await sim.opening()
    t = await sim.reply(sim.floor - 10)
    assert not t.agreed and t.price >= sim.floor


async def test_stubborn_barely_moves_and_never_passes_its_firm_floor():
    _, stub = await play("stubborn", [560] * 20)
    _, friend = await play("friendly", [560] * 20)
    stub_drop = stub[0].price - stub[-1].price
    friend_drop = friend[0].price - friend[-1].price
    assert stub[-1].price >= MEDIAN * 1.0
    assert stub_drop < friend_drop


async def test_pushy_concedes_slower_than_friendly():
    _, push = await play("pushy", [560] * 3)
    _, friend = await play("friendly", [560] * 3)
    push_drop = (push[0].price - push[-1].price) / push[0].price
    friend_drop = (friend[0].price - friend[-1].price) / friend[0].price
    assert push_drop < friend_drop


async def test_no_counter_means_the_vendor_repeats_its_price():
    sim = VendorSim("friendly", MEDIAN)
    await sim.opening()
    t = await sim.reply(None)
    assert t.price == sim.opening_price and not t.agreed


# ---------------------------------------------------------------- repeatable

@pytest.mark.parametrize("name", NAMES)
async def test_same_seed_plays_the_same_vendor(name):
    _, a = await play(name, [560, 600, 640], seed=5)
    _, b = await play(name, [560, 600, 640], seed=5)
    assert [t.model_dump() for t in a] == [t.model_dump() for t in b]


async def test_a_different_seed_changes_the_wording_or_the_attack_order():
    _, a = await play("attacker", [560, 600], seed=1)
    _, b = await play("attacker", [560, 600], seed=2)
    assert [t.text for t in a] != [t.text for t in b]


# ---------------------------------------------------------------- the lies and attacks

async def test_liar_always_mentions_a_made_up_price_that_is_not_its_own_offer():
    _, turns = await play("liar", [560, 600, 640, 660])
    for t in turns:
        assert t.fake_claim_price and t.fake_claim_price >= MEDIAN * 1.29
        assert format_price(t.fake_claim_price) in t.text
        assert abs(t.fake_claim_price - t.price) > 1
        assert t.price < t.fake_claim_price


async def test_attacker_adds_one_attack_to_every_message_and_labels_it():
    _, turns = await play("attacker", [560] * 5)
    for t in turns:
        assert t.attack_kind and t.attack_level in ("obvious", "sneaky") and t.expected_verdict
        assert any(a[3] in t.text for a in ATTACKS)


async def test_attacker_uses_every_attack_exactly_once_before_repeating():
    sim = VendorSim("attacker", MEDIAN, seed=4)
    await sim.opening()
    for _ in range(len(ATTACKS) - 1):
        await sim.reply(560)
    assert len(sim.history) == len(ATTACKS)
    for _, _, _, attack_text in ATTACKS:
        assert sum(attack_text in turn.text for turn in sim.history) == 1, attack_text


@pytest.mark.parametrize("name", ["friendly", "pushy", "liar", "stubborn"])
async def test_only_the_attacker_attacks(name):
    _, turns = await play(name, [560, 600])
    assert all(t.attack_kind is None and t.expected_verdict is None for t in turns)


@pytest.mark.parametrize("name", ["friendly", "pushy", "attacker", "stubborn"])
async def test_only_the_liar_lies(name):
    _, turns = await play(name, [560, 600])
    assert all(t.fake_claim_price is None for t in turns)


async def test_pushy_adds_pressure_until_the_vendor_agrees():
    sim = VendorSim("pushy", MEDIAN, seed=1)
    first = await sim.opening()
    assert any(u in first.text for u in PERSONAS["pushy"].urgency)
    agreed = await sim.reply(sim.opening_price)
    assert agreed.agreed and not any(u in agreed.text for u in PERSONAS["pushy"].urgency)


async def test_every_simulated_message_is_marked_simulated():
    _, turns = await play("friendly", [560, 600])
    assert all(t.simulated for t in turns)


# ---------------------------------------------------------------- the attack library

def test_attack_library_is_labelled_correctly():
    assert len(ATTACKS) >= 30
    for kind, level, expected, text in ATTACKS:
        assert level in ("obvious", "sneaky")
        assert expected in ("injection", "sensitive_request", "payment_risk", "suspicious_link")
        assert kind and text.strip()


@pytest.mark.parametrize(("kind", "level", "expected", "text"), [a for a in ATTACKS if a[1] == "obvious"])
def test_obvious_attacks_are_caught_by_the_rules(kind, level, expected, text):
    assert strongest(scan(text)[0]) == expected, text


@pytest.mark.parametrize(("kind", "level", "expected", "text"), [a for a in ATTACKS if a[1] == "sneaky"])
def test_sneaky_attacks_really_dodge_the_rules(kind, level, expected, text):
    # If the rules catch it, it is not sneaky. Only the model layer should be able to flag these.
    assert strongest(scan(text)[0]) == "ok", text


# ---------------------------------------------------------------- the model only writes wording

class FakeWriter:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    async def complete_json(self, role, system, user, schema, deal_id=None):
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return Sentence(text=self.answer)


async def test_model_wording_is_used_when_it_states_exactly_the_right_price():
    sim = VendorSim("friendly", MEDIAN, item="Dell XPS 15", seed=1, llm=FakeWriter("Hey there! It is $735 for that laptop."))
    t = await sim.opening()
    assert t.text.startswith("Hey there!") and t.price == 735


@pytest.mark.parametrize(
    "bad",
    [
        "It is $700 for that laptop.",  # wrong price
        "It is $735, or $600 if you pay today.",  # a second price the code did not choose
        "Great laptop, great price.",  # no price
        "x" * 400 + " $735",  # far too long
        "",
    ],
)
async def test_model_wording_with_wrong_numbers_is_thrown_away(bad):
    sim = VendorSim("friendly", MEDIAN, item="Dell XPS 15", seed=1, llm=FakeWriter(bad))
    t = await sim.opening()
    assert t.text != bad and "$735" in t.text
    assert [round(p.value) for p in extract_prices(t.text)] == [735]


async def test_model_failure_falls_back_to_the_template():
    sim = VendorSim("friendly", MEDIAN, item="Dell XPS 15", seed=1, llm=FakeWriter(LLMError("down")))
    t = await sim.opening()
    assert "$735" in t.text


async def test_prices_are_identical_with_or_without_a_model():
    counters = [560, 600, 640]
    _, plain = await play("liar", counters, seed=9)
    _, worded = await play("liar", counters, seed=9, llm=FakeWriter("Sure thing, it is $875."))
    assert [t.price for t in plain] == [t.price for t in worded]
    assert [t.fake_claim_price for t in plain] == [t.fake_claim_price for t in worded]


# ---------------------------------------------------------------- small helpers

def test_reply_delay_is_random_in_the_demo_and_zero_in_evaluation():
    rng = random.Random(1)
    demo = [reply_delay(rng, "demo") for _ in range(50)]
    assert all(1.0 <= d <= 3.0 for d in demo) and len(set(demo)) > 10
    assert reply_delay(rng, "eval") == 0.0


def test_format_price():
    assert format_price(880) == "$880"
    assert format_price(1200) == "$1,200"
    assert format_price(195000, "PKR") == "PKR 195,000"
    assert format_price(49.5) == "$49.50"
