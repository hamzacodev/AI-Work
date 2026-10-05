import ast
import random
from itertools import pairwise
from pathlib import Path

import pytest

from app.guardrails.limit_checker import Context, check_outgoing, compute_ceiling
from app.negotiation.strategy import (
    Situation,
    compute_counter,
    decide,
    floor_price,
    next_stall_count,
    step_for,
    target_price,
)
from app.simulator.personas import PERSONAS
from app.simulator.vendor_sim import VendorSim

# The usual case: you will pay up to 800, the market is 640 to 790 around 700.
BASE = {
    "max_price": 800.0,
    "research_low": 640.0,
    "research_median": 700.0,
    "research_high": 790.0,
    "research_confidence": "medium",
}


def sit(**over) -> Situation:
    return Situation(**{**BASE, **over})


# ---------------------------------------------------------------- the numbers


def test_target_is_95_percent_of_the_median_kept_inside_the_market_low_and_the_ceiling():
    assert target_price(640, 700, 760) == pytest.approx(665)  # 700 x 0.95
    assert target_price(680, 700, 760) == 680  # never below the market low
    assert target_price(640, 900, 760) == 760  # never above the ceiling
    assert target_price(800, 900, 760) == 760  # if even the low is above the ceiling, the ceiling wins


@pytest.mark.parametrize(("value", "expected"), [(759.99, 759.0), (100.0, 100.0), (99.999, 99.99), (4.567, 4.56), (0.0, 0.0)])
def test_prices_are_rounded_down(value, expected):
    assert floor_price(value) == expected


def test_a_step_is_one_unit_or_one_percent_of_the_vendors_offer():
    assert step_for(50) == 1.0
    assert step_for(880) == pytest.approx(8.8)


@pytest.mark.parametrize(
    ("previous", "new", "count", "expected"),
    [(None, 700, 0, 0), (700, 700, 0, 1), (700, 700, 1, 2), (700, 699.995, 1, 2), (700, 690, 3, 0), (700, None, 2, 0)],
)
def test_counting_how_often_the_vendor_repeats_the_same_price(previous, new, count, expected):
    assert next_stall_count(previous, new, count) == expected


# ---------------------------------------------------------------- the counter formula
# compute_counter(vendor_offer, ceiling, market_median, last_counter)


def test_your_example_vendor_asks_800_and_the_market_is_700_so_the_agent_opens_near_650():
    first = compute_counter(800, 760, 700, None)
    assert first == 651  # 93% of the market price: below the market, the way a real buyer starts
    assert first < 700  # below the market price
    assert first < 800  # and far below what the vendor asks


def test_the_first_counter_is_93_percent_of_the_market_price_whatever_the_vendor_asks():
    assert compute_counter(880, 760, 700, None) == 651
    assert compute_counter(2000, 760, 700, None) == 651


def test_if_the_vendors_price_is_already_close_the_counter_stays_one_step_below_it():
    assert compute_counter(660, 760, 700, None) == 651  # anchor is below 660 minus a step
    assert compute_counter(655, 760, 700, None) == 648  # 655 minus a step of 6.55, rounded down


def test_the_agent_never_offers_more_than_the_market_price_on_its_own():
    for last in (None, 600, 651, 690, 699):
        c = compute_counter(2000, 760, 700, last)
        assert c <= 700


def test_if_your_budget_is_below_the_market_the_ceiling_is_the_reference():
    # market 900 but the ceiling is 760: start at 93% of 760 and never pass 760
    assert compute_counter(2000, 760, 900, None) == 706
    assert compute_counter(2000, 760, 900, 750) <= 760


def test_the_counter_never_goes_above_the_vendors_price_minus_a_step():
    c = compute_counter(660, 760, 700, 650)
    assert c <= 660 - step_for(660) + 0.001


def test_later_counters_close_30_percent_of_the_gap_to_the_market_price():
    # cap = 700. From 651: 651 + 0.3 x 49 = 665.7, rounded down
    assert compute_counter(880, 760, 700, 651) == 665
    assert compute_counter(880, 760, 700, 665) == 675  # 665 + 0.3 x 35 = 675.5


def test_a_counter_never_moves_down():
    assert compute_counter(880, 760, 700, 695) >= 695
    assert compute_counter(690, 760, 700, 680) >= 680  # even when the cap has fallen to 683


def test_no_counter_when_there_is_no_room():
    assert compute_counter(1, 760, 700, None) is None  # cap would be below zero


def test_rounding_never_lifts_a_counter_over_the_cap():
    for offer in (801.7, 799.4, 903.3, 777.77, 702.2):
        c = compute_counter(offer, 760, 700, None)
        assert c <= min(700, offer - step_for(offer))


# ---------------------------------------------------------------- the decision, rule by rule


def test_an_injection_blocks_the_vendor_and_beats_everything():
    d = decide(sit(safety_verdict="injection", vendor_offer=500, research_confidence=None))
    assert d.action == "block" and d.counter_price is None


@pytest.mark.parametrize("verdict", ["ok", "sensitive_request", "payment_risk", "suspicious_link"])
def test_other_safety_verdicts_do_not_stop_the_negotiation_by_themselves(verdict):
    assert decide(sit(safety_verdict=verdict, vendor_offer=880)).action == "counter"


def test_a_message_the_safety_guard_wants_reviewed_goes_to_the_user():
    assert decide(sit(safety_needs_user=True, vendor_offer=880)).action == "needs_you"


def test_no_research_means_negotiate_from_the_vendors_own_prices():
    d = decide(sit(research_confidence=None, research_low=None, research_median=None, vendor_offer=880))
    assert d.action == "counter" and "No trusted market price" in d.reason
    assert d.counter_price < 880 and d.counter_price <= d.ceiling  # still under the vendor's price and the ceiling


def test_low_confidence_research_means_negotiate_from_the_vendors_own_prices():
    d = decide(sit(research_confidence="low", vendor_offer=880))
    assert d.action == "counter" and d.counter_price <= d.ceiling


def test_without_a_market_price_a_vendor_is_still_told_about_a_lower_competing_price():
    d = decide(sit(research_confidence="low", vendor_offer=1500, best_other_offer=1390.0))
    assert d.action in ("counter", "leverage") and d.leverage_price == 1390.0  # the competing price is shared as a number


def test_without_a_market_price_prices_far_above_the_maximum_still_get_a_counter_below_the_ceiling():
    d = decide(sit(research_confidence=None, research_low=None, research_median=None, max_price=1089.0, vendor_offer=1400.0))
    assert d.action in ("counter", "needs_you") and (d.counter_price or 0) <= 1089 * 0.95


def test_an_unreadable_offer_means_ask_the_user():
    assert decide(sit(offer_parse_failed=True, vendor_offer=None)).action == "needs_you"


def test_no_price_yet_means_send_the_first_message_without_numbers():
    d = decide(sit(vendor_offer=None))
    assert d.action == "first_message" and d.counter_price is None


def test_a_price_at_or_below_the_target_asks_the_user_and_recommends_accepting():
    d = decide(sit(vendor_offer=665, offers_so_far=(880, 665)))
    assert d.action == "needs_you" and d.recommendation.action == "accept"
    assert "Good price reached" in d.reason


def test_a_price_just_above_the_target_still_gets_a_counter():
    assert decide(sit(vendor_offer=700)).action == "counter"


def test_the_vendor_meeting_our_last_counter_stops_the_negotiation():
    d = decide(sit(vendor_offer=651, last_counter=651, rounds=1, offers_so_far=(880, 651)))
    assert d.action == "needs_you" and d.recommendation.action == "accept"  # 651 is below the market price


def test_a_vendor_within_one_step_of_our_last_counter_stops_too():
    d = decide(sit(vendor_offer=755, last_counter=748, rounds=1))  # gap 7 is less than a step of 7.55
    assert d.action == "needs_you"


def test_after_the_last_round_ask_the_user_with_the_best_offer():
    d = decide(sit(vendor_offer=690, last_counter=675, rounds=3, offers_so_far=(880, 800, 690)))
    assert d.action == "needs_you" and "3 rounds used" in d.reason and "$690" in d.reason
    assert d.recommendation.action == "accept"  # 690 is below the market price of 700


def test_after_the_last_round_an_offer_above_the_maximum_is_not_recommended_for_acceptance():
    d = decide(sit(vendor_offer=850, last_counter=748, rounds=3))
    assert d.recommendation.action == "counter"
    far = decide(sit(vendor_offer=1100, last_counter=748, rounds=3))
    assert far.recommendation.action == "reject"


def test_a_vendor_repeating_the_same_price_stops_the_negotiation():
    d = decide(sit(vendor_offer=880, last_counter=748, rounds=1, stall_count=2))
    assert d.action == "needs_you" and "repeating" in d.reason


def test_a_budget_far_below_the_market_is_reported():
    d = decide(Situation(max_price=300, research_low=640, research_median=700, research_high=790, research_confidence="high", vendor_offer=880))
    assert d.action == "needs_you" and "budget looks too low" in d.reason and d.recommendation.action == "reject"


def test_at_the_market_price_the_agent_stops_instead_of_repeating_the_same_counter():
    d = decide(sit(vendor_offer=770, last_counter=700, rounds=2))  # 700 is the most it offers on its own
    assert d.action == "needs_you" and "the most it will offer on its own" in d.reason
    assert d.recommendation.action == "counter"  # 770 is above the market price: not a good deal yet


def test_the_decision_always_carries_the_ceiling_and_target():
    d = decide(sit(vendor_offer=880))
    assert d.ceiling == compute_ceiling(800) == 760.0 and d.target == pytest.approx(665)


def test_a_vendor_offer_above_the_maximum_is_never_recommended_for_acceptance_at_any_stage():
    for rounds in (0, 1, 2, 3):
        for stall in (0, 2):
            d = decide(sit(vendor_offer=900, last_counter=700 if rounds else None, rounds=rounds, stall_count=stall))
            assert not (d.recommendation and d.recommendation.action == "accept")


def test_the_reason_is_plain_words_with_formatted_money():
    d = decide(sit(vendor_offer=800, last_counter=748, rounds=3, offers_so_far=(880, 800), currency="PKR"))
    assert "PKR 800" in d.reason


# ---------------------------------------------------------------- safety properties over many random negotiations


def run_negotiation(persona: str, seed: int, max_price=800.0, median=700.0, max_rounds=3):
    """Plays one negotiation against a fake vendor. Returns every Decision and the counters the agent sent."""
    import asyncio

    async def go():
        sim = VendorSim(persona, median, seed=seed)
        turn = await sim.opening()
        offers: list[float] = []
        last_counter: float | None = None
        rounds = stall = 0
        previous: float | None = None
        decisions, counters = [], []
        for _ in range(30):  # a safety stop. A negotiation must end long before this.
            offers.append(turn.price)
            stall = next_stall_count(previous, turn.price, stall)
            previous = turn.price
            d = decide(
                Situation(
                    max_price=max_price, max_rounds=max_rounds, research_low=median * 0.9, research_median=median,
                    research_high=median * 1.1, research_confidence="medium", vendor_offer=turn.price,
                    offers_so_far=tuple(offers), last_counter=last_counter, rounds=rounds, stall_count=stall,
                )
            )  # fmt: skip
            decisions.append(d)
            if d.action != "counter":
                break
            counters.append(d.counter_price)
            last_counter, rounds = d.counter_price, rounds + 1
            turn = await sim.reply(d.counter_price)
        return decisions, counters, offers

    return asyncio.run(go())


@pytest.mark.parametrize("persona", list(PERSONAS))
@pytest.mark.parametrize("seed", range(8))
def test_every_negotiation_ends_and_every_counter_is_safe(persona, seed):
    decisions, counters, offers = run_negotiation(persona, seed)
    ceiling = compute_ceiling(800)
    assert decisions[-1].action in ("needs_you", "block"), "the negotiation must stop by itself"
    assert len(counters) <= 3, "never more than max_rounds counters"
    assert all(c <= ceiling for c in counters), "never above the ceiling"
    assert all(b >= a for a, b in pairwise(counters)), "never moves down"
    assert all(c < o for c, o in zip(counters, offers, strict=False)), "always below the vendor's current offer"
    assert all(c < 800 for c in counters), "never reaches the maximum"
    assert all(c <= 700 for c in counters), "never offers more than the market price on its own"
    assert not counters or counters[0] < 700, "the first counter is below the market price"


@pytest.mark.parametrize("seed", range(20))
def test_random_situations_never_break_the_guarantees(seed):
    rng = random.Random(seed)
    for _ in range(50):
        max_price = rng.choice([50, 300, 800, 5000, 250000])
        median = max_price * rng.uniform(0.4, 1.2)
        offer = max_price * rng.uniform(0.3, 2.0)
        last = None if rng.random() < 0.4 else max_price * rng.uniform(0.2, 0.94)
        d = decide(
            Situation(
                max_price=max_price, research_low=median * 0.85, research_median=median, research_high=median * 1.15,
                research_confidence="medium", vendor_offer=offer, last_counter=last, rounds=rng.randint(0, 4),
                stall_count=rng.randint(0, 3),
            )
        )  # fmt: skip
        ceiling = compute_ceiling(max_price)
        assert d.action in ("block", "needs_you", "first_message", "counter")
        if d.action == "counter":
            assert 0 < d.counter_price <= min(ceiling, median) < max_price
            assert d.counter_price < offer
            assert last is None or d.counter_price >= last
        if d.recommendation and d.recommendation.action == "accept":
            assert offer <= max_price
            assert offer <= median + 0.01, "the default advice accepts only at or below the market price"


@pytest.mark.parametrize("seed", range(10))
def test_every_counter_passes_the_limit_checker(seed):
    """The strategy and the Limit Checker are separate pieces of code. They must agree."""
    _, counters, offers = run_negotiation("pushy", seed)
    last = None
    for i, c in enumerate(counters):
        ctx = Context(
            max_price=800, recipient="a@x.example.com", vendor_contacts=frozenset({"a@x.example.com"}),
            counter_price=c, previous_counter=last, vendor_offer=offers[i], vendor_prices=tuple(offers[: i + 1]),
            research_figures=(630, 700, 770), rounds=i + 1,
        )  # fmt: skip
        r = check_outgoing(f"Thank you. Could you do ${c:.0f}?", ctx)
        assert r.allowed, (c, r.violations)
        last = c


# ---------------------------------------------------------------- outcomes against each persona


def test_a_friendly_vendor_ends_in_a_recommendation_to_accept():
    decisions, _, _ = run_negotiation("friendly", 1)
    assert decisions[-1].action == "needs_you" and decisions[-1].recommendation.action == "accept"


def test_a_stubborn_vendor_is_never_recommended_for_acceptance_above_the_maximum():
    decisions, _, offers = run_negotiation("stubborn", 1, max_price=700.0, median=700.0)
    last = decisions[-1]
    if offers[-1] > 700:
        assert last.recommendation.action != "accept"


# ---------------------------------------------------------------- this file stays free of AI code


def test_the_strategy_imports_no_ai_or_network_code():
    banned = {"openai", "anthropic", "httpx", "requests", "supabase", "tavily", "langgraph", "langchain", "app.core.llm", "app.core.db"}
    for f in (Path(__file__).resolve().parent.parent / "app" / "negotiation").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for n in names:
                assert n not in banned and n.split(".")[0] not in banned, f"{f.name} imports {n}"


# ---------------------------------------------------------------- the buyer wants to pay at or below the market price


def test_the_advice_accepts_only_at_or_below_the_market_price():
    assert decide(sit(vendor_offer=700, last_counter=651, rounds=3)).recommendation.action == "accept"
    assert decide(sit(vendor_offer=690, last_counter=651, rounds=3)).recommendation.action == "accept"


def test_a_price_above_the_market_is_advised_against_even_when_it_is_within_the_maximum():
    d = decide(sit(vendor_offer=790, last_counter=675, rounds=3, offers_so_far=(910, 790)))
    assert d.recommendation.action == "counter"
    assert "above the market price of $700" in d.recommendation.reason and "not a good deal yet" in d.recommendation.reason
    assert "accept it yourself" in d.recommendation.reason  # the user still decides


def test_a_price_far_above_the_maximum_is_still_a_reject():
    assert decide(sit(vendor_offer=1100, last_counter=675, rounds=3)).recommendation.action == "reject"


def test_the_old_behaviour_is_available_as_a_setting():
    d = decide(sit(vendor_offer=790, last_counter=675, rounds=3, accept_only_below_market=False))
    assert d.recommendation.action == "accept" and "within your maximum" in d.recommendation.reason


def test_a_price_above_the_maximum_is_never_accepted_in_either_mode():
    for flag in (True, False):
        d = decide(sit(vendor_offer=850, last_counter=675, rounds=3, accept_only_below_market=flag))
        assert d.recommendation.action != "accept"


@pytest.mark.parametrize("seed", range(10))
def test_in_every_fake_negotiation_accept_advice_is_at_or_below_the_market(seed):
    for persona in PERSONAS:
        decisions, _, offers = run_negotiation(persona, seed)
        last = decisions[-1]
        if last.recommendation and last.recommendation.action == "accept":
            assert offers[-1] <= 700.01, (persona, seed, offers)


# ---------------------------------------------------------------- patience with small talk


def test_the_first_small_talk_gets_only_a_friendly_reply_with_no_pressure():
    d = decide(sit(vendor_offer=800.0, no_new_price=True, messages_sent=1, casual_streak=1))
    assert d.action == "chat" and d.back_to_business is False


def test_small_talk_that_goes_on_gets_a_reply_and_a_way_back_to_the_price():
    d = decide(sit(vendor_offer=800.0, no_new_price=True, messages_sent=2, casual_streak=2, best_other_offer=690.0))
    assert d.action == "chat" and d.back_to_business is True
    assert d.leverage_price == 690.0  # a real competing price, a number only


def test_the_way_back_has_no_competing_price_when_there_is_none():
    d = decide(sit(vendor_offer=800.0, no_new_price=True, messages_sent=2, casual_streak=2))
    assert d.back_to_business is True and d.leverage_price is None


def test_a_plain_yes_is_a_confirmation_not_small_talk():
    from app.negotiation.strategy import is_affirmation

    assert all(is_affirmation(x) for x in ("yes", "Yes.", "ok sure", "okay", "correct", "yeah that's right", "sounds good"))
    assert not any(is_affirmation(x) for x in ("no", "ok what colour do you want?", "yes but only for $900 and with delivery today", "how are you?", "nope"))
    d = decide(sit(vendor_offer=260.0, no_new_price=True, messages_sent=2, affirmation=True, others_active=True))
    assert d.action == "hold" and d.stop_reason == "confirmed" and d.counter_price is None
    d = decide(sit(vendor_offer=260.0, no_new_price=True, messages_sent=2, affirmation=True))
    assert d.action == "needs_you" and d.stop_reason == "confirmed"  # nobody else is negotiating: it is your turn
