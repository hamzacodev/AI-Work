"""Leverage (the best offer we hold), firm prices and the hold rule: strategy, Negotiator and Limit Checker together."""

import random
import re

from app.agents.fact_checker import FactVerdict, StatementVerdict
from app.agents.fact_rules import Turn
from app.agents.negotiator import (
    Draft,
    NegotiationContext,
    check_numbers,
    leverage_sentence,
    limit_context_for,
    negotiate,
)
from app.guardrails.limit_checker import Context, check_outgoing, compute_ceiling
from app.negotiation.strategy import (
    FIRM_PUSH_LIMIT,
    Situation,
    compute_counter,
    decide,
    usable_leverage,
)
from app.negotiation.tactics import Tactics
from app.negotiation.tracker import VendorState, leverage_for

BASE = {"max_price": 800.0, "research_low": 640.0, "research_median": 700.0, "research_high": 790.0, "research_confidence": "medium"}


def sit(**over) -> Situation:
    return Situation(**{**BASE, **over})


# ---------------------------------------------------------------- the strategy with other vendors


def test_a_counter_mentions_the_best_offer_we_hold_and_never_goes_above_it():
    d = decide(sit(vendor_offer=870, best_other_offer=650))
    assert d.action == "counter" and d.leverage_price == 650
    assert d.counter_price < 650  # never offer more than the best price we already hold


def test_without_other_offers_nothing_changes():
    d = decide(sit(vendor_offer=870))
    assert d.action == "counter" and d.counter_price == 651 and d.leverage_price is None


def test_a_higher_other_offer_is_not_used_as_leverage():
    d = decide(sit(vendor_offer=800, best_other_offer=820))
    assert d.leverage_price is None


def test_an_other_offer_above_the_market_is_still_shared_because_it_is_a_real_price():
    d = decide(sit(vendor_offer=900, best_other_offer=730))  # 730 is above the market of 700, but another vendor really said it
    assert d.leverage_price == 730 and d.counter_price == 651  # our own counter is still capped by our limits


def test_a_far_too_low_other_offer_is_not_advertised():
    assert decide(sit(vendor_offer=800, best_other_offer=100)).leverage_price is None


def test_when_our_own_counter_is_already_above_the_best_offer_we_only_ask_them_to_beat_it():
    d = decide(sit(vendor_offer=720, best_other_offer=640, last_counter=651, rounds=1))
    assert d.action == "leverage" and d.counter_price is None and d.leverage_price == 640


def test_a_vendor_at_the_target_is_asked_to_beat_a_lower_offer_from_someone_else():
    d = decide(sit(vendor_offer=640, best_other_offer=630, rounds=1, last_counter=620))
    assert d.action == "leverage" and d.leverage_price == 630


def test_the_same_leverage_number_is_not_repeated():
    d = decide(sit(vendor_offer=640, best_other_offer=630, last_leverage=630, others_active=True))
    assert d.action == "hold"


def test_leverage_uses_up_rounds():
    d = decide(sit(vendor_offer=720, best_other_offer=640, last_counter=651, rounds=3))
    assert d.action == "needs_you" and d.stop_reason == "round_limit"


def test_a_good_price_holds_while_other_vendors_are_still_negotiating():
    d = decide(sit(vendor_offer=640, others_active=True))
    assert d.action == "hold" and d.recommendation.action == "accept" and d.stop_reason == "good_price"
    assert "Waiting for the other vendors" in d.reason


def test_a_good_price_asks_the_user_when_nobody_else_is_negotiating():
    d = decide(sit(vendor_offer=640, others_active=False))
    assert d.action == "needs_you" and d.recommendation.action == "accept"


def test_round_limit_and_stalls_also_hold_for_the_others():
    assert decide(sit(vendor_offer=800, rounds=3, last_counter=700, others_active=True)).action == "hold"
    assert decide(sit(vendor_offer=800, stall_count=2, rounds=1, last_counter=651, others_active=True)).stop_reason == "stalled"


def test_real_problems_never_hold_they_still_ask_the_user():
    assert decide(sit(vendor_offer=None, offer_parse_failed=True, others_active=True)).action == "needs_you"
    # no trusted market price no longer stops the agent: it negotiates from the vendors' own prices (see test_negotiation.py)
    assert decide(sit(research_confidence="low", vendor_offer=800.0, others_active=True)).action == "counter"
    assert decide(sit(safety_needs_user=True, others_active=True)).action == "needs_you"
    assert decide(sit(safety_verdict="injection", others_active=True)).action == "block"


# ---------------------------------------------------------------- a vendor who says "final price"


def test_a_firm_vendor_gets_up_to_two_more_tries():
    d = decide(sit(vendor_offer=840, firm=True, firm_pushes=0))
    assert d.action == "counter" and d.firm_push and d.counter_price == 651
    d = decide(sit(vendor_offer=840, firm=True, firm_pushes=1, last_counter=651, rounds=1))
    assert d.action == "counter" and d.firm_push and d.counter_price == 665


def test_after_the_tries_a_firm_vendor_is_left_alone_but_the_chat_stays_open():
    d = decide(sit(vendor_offer=840, firm=True, firm_pushes=FIRM_PUSH_LIMIT, last_counter=675, rounds=2))
    assert d.action == "close" and d.stop_reason == "firm_price" and d.counter_price is None  # a polite goodbye, then silence
    d = decide(sit(vendor_offer=840, firm=True, firm_pushes=FIRM_PUSH_LIMIT, last_counter=675, rounds=2, others_active=True))
    assert d.action == "close" and d.stop_reason == "firm_price"
    d = decide(sit(vendor_offer=840, firm=True, firm_pushes=FIRM_PUSH_LIMIT, last_counter=675, rounds=2, others_active=True, stopped=True))
    assert d.action == "hold" and d.stop_reason == "firm_price"  # the goodbye was already sent: silent


def test_a_firm_vendor_with_a_good_price_is_still_a_candidate_for_the_best_deal():
    d = decide(sit(vendor_offer=640, firm=True, firm_pushes=FIRM_PUSH_LIMIT))
    assert d.recommendation.action == "accept"


def test_a_firm_vendor_who_used_up_the_tries_is_still_told_once_about_a_lower_offer():
    d = decide(sit(vendor_offer=720, firm=True, firm_pushes=FIRM_PUSH_LIMIT, best_other_offer=640, last_counter=651, rounds=2))
    assert d.action == "leverage" and d.leverage_price == 640  # new information, so one message is fine
    again = decide(sit(vendor_offer=720, firm=True, firm_pushes=FIRM_PUSH_LIMIT, best_other_offer=640, last_leverage=640, last_counter=651, rounds=2))
    assert again.action == "close"  # never the same price twice


def test_a_firm_vendor_is_asked_with_leverage_too():
    d = decide(sit(vendor_offer=840, firm=True, firm_pushes=0, best_other_offer=650))
    assert d.leverage_price == 650 and d.firm_push


# ---------------------------------------------------------------- the Limit Checker


def lc(**over) -> Context:
    base = {"max_price": 800.0, "recipient": "v@x.com", "vendor_contacts": frozenset({"v@x.com"})}
    return Context(**{**base, **over})


def test_the_limit_checker_allows_the_competing_offer_only_when_it_is_given():
    msg = "I already have an offer of $640 for this item. Can you do better?"
    assert not check_outgoing(msg, lc(vendor_offer=720)).allowed
    assert check_outgoing(msg, lc(vendor_offer=720, competing_offer=640)).allowed


def test_the_competing_offer_can_never_be_the_maximum():
    msg = "I already have an offer of $800 for this item."
    r = check_outgoing(msg, lc(vendor_offer=900, competing_offer=800))
    assert not r.allowed and any("max_price_leak" in v for v in r.violations)


def test_another_price_is_still_blocked_next_to_the_competing_offer():
    r = check_outgoing("I have an offer of $640. Could you do $500?", lc(vendor_offer=720, competing_offer=640))
    assert not r.allowed


# ---------------------------------------------------------------- the Negotiator


VENDOR = "sales@techhub.example.com"


def ctx(decision, **over) -> NegotiationContext:
    base = {
        "decision": decision, "item": "Dell XPS 15", "currency": "USD", "max_price": 800.0, "recipient": VENDOR,
        "vendor_contacts": frozenset({VENDOR}), "conversation": [Turn(sender="vendor", text="OK, $720.")],
        "vendor_offer": 720.0, "vendor_prices": (720.0,), "research_low": 640.0, "research_median": 700.0,
        "research_high": 790.0, "tactics": Tactics(),
    }
    base.update(over)
    return NegotiationContext(**base)


class FakeLLM:
    def __init__(self, drafts):
        self.drafts = list(drafts)
        self.prompts: list[str] = []

    async def complete_json(self, role, system, user, schema, deal_id=None):
        if schema is Draft:
            self.prompts.append(system)
            return Draft(message=self.drafts.pop(0) if len(self.drafts) > 1 else self.drafts[0])
        statements = re.findall(r"^(\d+)\. (.*)$", user, re.MULTILINE)
        return FactVerdict(statements=[StatementVerdict(statement=int(n), supported=True, problem="") for n, _ in statements])


def lever_decision():
    return decide(sit(vendor_offer=720, best_other_offer=640, last_counter=651, rounds=1))


async def test_a_leverage_message_states_the_best_offer_and_no_name():
    d = lever_decision()
    c = ctx(d)
    assert leverage_sentence(c) == "I already have an offer of $640 for this item."
    draft = "I see you have lowered the price. I already have an offer of $640 for this item. Can you do better than that?"
    r = await negotiate(c, FakeLLM([draft]))
    assert r.ok and r.message == draft and r.rewrites == 0


async def test_a_leverage_draft_without_the_exact_sentence_is_rewritten():
    c = ctx(lever_decision())
    good = "I already have an offer of $640 for this item. Can you do better than that?"
    r = await negotiate(c, FakeLLM(["Another seller is cheaper. Can you do better?", good]))
    assert r.ok and r.message == good and r.rewrites == 1


async def test_a_leverage_draft_with_a_made_up_number_is_never_sent():
    # The made-up number is never sent. The agent keeps talking with a plain template built from the real numbers.
    c = ctx(lever_decision())
    bad = "I already have an offer of $640 for this item. Could you do $500?"
    r = await negotiate(c, FakeLLM([bad]))
    assert r.ok and r.message is not None and "$500" not in r.message and "$640" in r.message
    assert check_numbers(r.message, c) == []


async def test_a_bad_counter_draft_falls_back_to_a_template_so_the_agent_keeps_talking():
    d = decide(sit(vendor_offer=900))
    c = ctx(d, vendor_offer=900.0, vendor_prices=(900.0,))
    r = await negotiate(c, FakeLLM(["The price is 9530 dollars.", "Still 9530.", "9530!"]))
    assert r.ok and f"{d.counter_price:g}" in (r.message or "") and "9530" not in (r.message or "")


async def test_a_counter_with_leverage_contains_both_numbers():
    d = decide(sit(vendor_offer=870, best_other_offer=650))
    c = ctx(d, vendor_offer=870.0, vendor_prices=(870.0,), tactics=Tactics(good_rate_line=False, ask_extras=False, ask_best_price=False, meet_halfway=False))
    ok = f"I already have an offer of $650 for this item. Could you do ${d.counter_price:g}?"
    assert check_numbers(ok, c) == []
    assert check_numbers(f"Could you do ${d.counter_price:g}?", c)  # the leverage sentence is missing


async def test_the_system_prompt_for_leverage_has_no_other_vendor_names_and_no_maximum():
    llm = FakeLLM(["I already have an offer of $640 for this item. Can you do better than that?"])
    await negotiate(ctx(lever_decision(), vendor_offer=720.0), llm)
    p = llm.prompts[0]
    assert "$640" in p and "Do not say who" in p and "800" not in p


def test_the_limit_context_carries_the_competing_offer_and_counts_the_round():
    c = ctx(lever_decision(), rounds=1)
    lim = limit_context_for(c)
    assert lim.competing_offer == 640 and lim.rounds == 2


async def test_a_firm_push_tells_the_writer_to_acknowledge_politely():
    d = decide(sit(vendor_offer=840, firm=True, firm_pushes=0))
    llm = FakeLLM(["I understand. Could you do $651?"])
    await negotiate(ctx(d, vendor_offer=840.0, vendor_prices=(840.0,), tactics=Tactics(good_rate_line=False, ask_extras=False, ask_best_price=False, meet_halfway=False)), llm)
    assert "price is final" in llm.prompts[0]


# ---------------------------------------------------------------- properties over many random deals


def test_over_many_random_deals_no_counter_or_leverage_breaks_the_rules():
    rng = random.Random(7)
    for _ in range(1500):
        offer = rng.randint(500, 1100)
        best = rng.choice([None, rng.randint(250, 900)])
        last = rng.choice([None, rng.randint(560, 700)])
        s = sit(
            vendor_offer=float(offer), best_other_offer=None if best is None else float(best), last_counter=None if last is None else float(last),
            rounds=0 if last is None else rng.randint(1, 3), firm=rng.random() < 0.3, firm_pushes=rng.randint(0, 3), others_active=rng.random() < 0.5,
            stall_count=rng.randint(0, 2),
        )
        d = decide(s)
        ceiling = compute_ceiling(800.0)
        if d.counter_price is not None:
            assert d.counter_price <= ceiling and d.counter_price <= 700 and d.counter_price < offer
            if last is not None:
                assert d.counter_price >= last
            if d.leverage_price is not None:
                assert d.counter_price < d.leverage_price  # never offer above the best price we hold
        if d.leverage_price is not None:
            assert d.leverage_price < offer and d.leverage_price >= 350 and d.leverage_price != 800
            assert d.leverage_price == best
        if d.action == "hold":
            assert s.others_active
        if d.action == "leverage":
            assert d.counter_price is None and s.rounds < s.max_rounds


def test_every_decision_message_passes_the_real_limit_checker():
    rng = random.Random(11)
    for _ in range(500):
        offer, best = rng.randint(600, 1000), rng.randint(450, 700)
        d = decide(sit(vendor_offer=float(offer), best_other_offer=float(best)))
        if d.action not in ("counter", "leverage"):
            continue
        parts = []
        if d.leverage_price is not None:
            parts.append(f"I already have an offer of ${d.leverage_price:g} for this item.")
        if d.counter_price is not None:
            parts.append(f"Could you do ${d.counter_price:g}?")
        r = check_outgoing(" ".join(parts), lc(vendor_offer=float(offer), counter_price=d.counter_price, competing_offer=d.leverage_price))
        assert r.allowed, (d, r.violations)


def test_tracker_and_strategy_agree_on_leverage():
    states = [VendorState("a", "A", 870), VendorState("b", "B", 650), VendorState("c", "C", 900)]
    lever = leverage_for("a", states, 700, 760)
    assert usable_leverage(lever, 870, 700, 760) == lever == 650


def test_compute_counter_without_an_extra_cap_is_unchanged():
    assert compute_counter(800, 760, 700, None) == 651
    assert compute_counter(800, 760, 700, None, extra_cap=640 - 6.4) < 640




def test_a_message_without_a_price_gets_a_chat_reply_not_another_counter():
    d = decide(sit(vendor_offer=880, last_counter=651, rounds=1, no_new_price=True, messages_sent=2))
    assert d.action == "chat" and d.counter_price is None


def test_a_vendor_who_writes_after_the_accept_box_showed_still_gets_a_reply():
    # the user wants the agent to answer, and the box to go away (the chat is negotiating again)
    d = decide(sit(vendor_offer=880, last_counter=651, rounds=1, no_new_price=True, messages_sent=2, stopped=True))
    assert d.action == "chat"


def test_a_no_after_the_goodbye_gets_silence_not_a_second_goodbye():
    d = decide(sit(vendor_offer=880, last_counter=651, rounds=1, no_new_price=True, refusal=True, messages_sent=3, stopped=True))
    assert d.action == "hold"


def test_no_chat_reply_before_the_first_message_and_never_over_an_injection():
    assert decide(sit(vendor_offer=None, no_new_price=True, messages_sent=0)).action == "first_message"
    assert decide(sit(vendor_offer=880, no_new_price=True, messages_sent=1, safety_verdict="injection")).action == "block"


def test_a_price_close_to_the_lowest_market_price_is_not_chased_with_more_counters():
    # the market low is 640: an offer of 660 is within 5 percent of it, so asking for less again would only repeat the cycle
    d = decide(sit(vendor_offer=660, last_counter=620, rounds=1, max_price=600))
    assert d.action in ("hold", "needs_you") and d.stop_reason == "near_market_low"


def test_a_price_close_to_the_low_still_tells_the_vendor_about_a_lower_offer_we_hold():
    d = decide(sit(vendor_offer=665, best_other_offer=650, last_counter=620, rounds=1, max_price=600))
    assert d.action == "leverage" and d.leverage_price == 650


def test_a_clear_no_without_a_price_gets_a_polite_goodbye_not_another_question():
    from app.negotiation.strategy import is_refusal

    for text in ("nope", "not for now", "Nope i cannot", "no more negotiations", "it is not possoble", "sorry i cannot"):
        assert is_refusal(text), text
    for text in ("no problem, let me check", "its strange how its possible", "are you interested?", "ok let me see"):
        assert not is_refusal(text), text
    d = decide(sit(vendor_offer=300, last_counter=261, rounds=1, no_new_price=True, refusal=True, messages_sent=2))
    assert d.action == "close" and d.stop_reason == "refused" and d.counter_price is None
    again = decide(sit(vendor_offer=300, last_counter=261, rounds=1, no_new_price=True, refusal=True, messages_sent=3, stopped=True))
    assert again.action != "close"  # the goodbye is sent once
