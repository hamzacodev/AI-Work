"""The negotiation strategy: what to do next, and what price to offer. Plain code, no AI.

In easy words: after every vendor message this file answers two questions.
  1. Should we keep negotiating, or stop and ask the user?
  2. If we keep going, what exact price do we offer?

The AI (the Negotiator) only writes the sentence around the price this file picks. It never chooses a number.
The rules follow docs/agents.md Part 1. Nothing here imports an AI or network library, and a test checks that.
"""

import math
import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from app.core.money import format_price
from app.guardrails.limit_checker import compute_ceiling

TARGET_RATIO = 0.95  # the "good enough" price is 95% of the market median
MARKET_CAP = True  # on its own the agent never offers more than the market price (you can always go higher yourself)
ANCHOR_RATIO = 0.93  # the first counter starts at 93% of the market price: below it, like a real buyer would
GAP_SHARE = 0.30  # each later counter closes 30% of the gap to the cap
MIN_BUDGET_RATIO = 0.5  # a cap below half the market price means the budget is far too low
FAR_ABOVE = 1.20  # an offer more than 20% above the maximum is not worth a counter
STALL_LIMIT = 2  # the vendor repeats the same price twice: stop
SAME_PRICE = 0.01
FIRM_PUSH_LIMIT = 2  # when a vendor says "final price", we try at most 2 more messages, then stop texting
NEAR_LOW_RATIO = 1.05  # a price within 5% of the LOWEST market price is already as good as the market gets
PSEUDO_LOW_RATIO = 0.85  # with no trusted market price, the "market low" is taken as 85% of the lowest vendor price
MIN_CREDIBLE_RATIO = 0.5  # a competing offer under half the market price is not used as leverage

CASUAL_PATIENCE = 2  # small talk gets this many vendor messages before the agent also brings the talk back to the price

# "hold" = stop texting this vendor, keep the chat open, and wait for the other vendors (nothing for the user to do yet)
# "leverage" = no counter price: only tell the vendor the best offer we hold and ask them to beat it
# "chat" = the vendor wrote something WITHOUT a price (a question, a complaint, small talk): answer like a person, no new price
# "close" = a polite goodbye ("we will get back to you") and the agent stops texting this vendor. The chat stays open, and the vendor is
#   written to again when another vendor gets a lower price (see tracker.reengage_candidates).
Action = Literal["block", "needs_you", "hold", "first_message", "counter", "leverage", "chat", "close"]
Advice = Literal["accept", "reject", "counter"]


@dataclass(frozen=True)
class Recommendation:
    action: Advice
    reason: str


@dataclass(frozen=True)
class Situation:
    """Everything the strategy needs. The agent loop fills it in from the database and the other steps."""

    max_price: float
    currency: str = "USD"
    ceiling_ratio: float = 0.95
    max_rounds: int = 3
    # research (None when research was unavailable)
    research_low: float | None = None
    research_median: float | None = None
    research_high: float | None = None
    research_confidence: Literal["low", "medium", "high"] | None = None
    # the Safety Guard's answer for this vendor message
    safety_verdict: str = "ok"
    safety_needs_user: bool = False
    # the vendor
    vendor_offer: float | None = None  # their latest price (None: they have not quoted one yet)
    offer_parse_failed: bool = False
    no_new_price: bool = False  # the vendor's last message has no price in it (read by the Offer Reader)
    refusal: bool = False  # ... and it is a clear no ("nope", "not for now", "cannot")
    messages_sent: int = 0  # how many messages the agent already wrote to this vendor
    affirmation: bool = False  # the vendor's message is just a "yes" (no price): they confirm, there is nothing new to ask
    upset: bool = False  # the vendor's message is unkind or unhappy: a kind reply only, no push back to the price
    casual_streak: int = 0  # how many vendor messages in a row had no price (small talk), counting the current one
    stopped: bool = False  # the agent already stopped texting this vendor (paused or waiting for you)
    offers_so_far: tuple[float, ...] = ()  # every price this vendor quoted, oldest first
    last_counter: float | None = None  # our previous counter to this vendor
    rounds: int = 0  # counters we already sent to this vendor
    stall_count: int = 0  # how many times in a row the vendor repeated the same price
    # The buyer wants to pay AT OR BELOW the market price. Above it, the advice is to keep negotiating, not to accept.
    accept_only_below_market: bool = True
    offer_credit: float = 0.0  # the value to the buyer of the free extras the vendor gives (see addons.py). What you PAY is still the price.
    # the other vendors (filled in from the Best Offer Tracker, see tracker.py)
    best_other_offer: float | None = None  # the lowest real price another vendor gave. Never a name.
    last_leverage: float | None = None  # the competing price we already told this vendor
    others_active: bool = False  # some other vendor is still being negotiated with
    # "this is our final price"
    firm: bool = False
    firm_pushes: int = 0  # messages we sent after the vendor said the price is final


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str  # plain words, shown on the dashboard
    counter_price: float | None = None
    recommendation: Recommendation | None = None
    ceiling: float = 0.0
    target: float | None = None
    leverage_price: float | None = None  # a competing price the message must state ("I already have an offer of ...")
    firm_push: bool = False  # the vendor said the price is final and this message tries once more
    stop_reason: str | None = None  # why we stopped texting: firm_price, round_limit, stalled, good_price, met_counter
    back_to_business: bool = False  # "chat" only: after the small-talk reply, send a SECOND message that returns to the price


# ---------------------------------------------------------------- the numbers


def floor_price(value: float) -> float:
    """Rounds DOWN: whole units for 100 or more, two decimals below. Down, so rounding can never push a
    counter above the ceiling or above the vendor's offer."""
    if value >= 100:
        return float(math.floor(value))
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def target_price(low: float, median: float, ceiling: float) -> float:
    """The good-enough price: 95% of the median, not below the market low, and never above the ceiling."""
    return min(ceiling, max(low, median * TARGET_RATIO))


def step_for(vendor_offer: float) -> float:
    return max(1.0, vendor_offer * 0.01)


def next_stall_count(previous_offer: float | None, new_offer: float | None, stall_count: int) -> int:
    """How many times in a row the vendor has repeated the same price."""
    if previous_offer is None or new_offer is None:
        return 0
    return stall_count + 1 if abs(new_offer - previous_offer) < SAME_PRICE else 0


def reference_price(median: float, ceiling: float) -> float:
    """The most the agent will offer on its own: the market price, and never above the ceiling."""
    return min(median, ceiling) if MARKET_CAP else ceiling


_REFUSAL = re.compile(
    r"(^\W*(no|nope|nah)\b(?!\s+(problem|worries))|\bnot (possible|possoble|for now|interested|able)\b|\bcan ?no?t\b|\bcan'?t\b|\bwon'?t\b|"
    r"\bno (more|way|negotiat\w*|deal)\b|\bimpossible\b|\bleast i can\b|\bmy last\b|\btake it or leave\b|\bnot now\b)",
    re.IGNORECASE,
)


_UPSET = re.compile(
    r"(\b(don'?t|do not|dont) like (you|this|it)\b|\b(annoying|stupid|idiot|useless|rude|waste of|hate you|shut up|go away|leave me|scam|fraud|cheat|angry|upset)\b|"
    r"\b(bad|poor|terrible|worst) (service|buyer|bot|agent)\b|\bstop (texting|messaging|bothering)\b)",
    re.IGNORECASE,
)


def is_upset(text: str) -> bool:
    """A short message that is unkind or unhappy ("i dont like you"). Plain code. The agent answers kindly and does not push the price."""
    return len(text.split()) <= 30 and bool(_UPSET.search(text))


_YES = re.compile(
    r"^\W*(yes|yeah|yep|yup|ya|sure|ok|okay|k|correct|right|exactly|confirmed|of course|alright|fine|agreed|deal|sounds good|that'?s right|absolutely)\b",
    re.IGNORECASE,
)


def is_affirmation(text: str) -> bool:
    """A very short "yes" ("yes", "ok sure", "correct"). Plain code. Only used when the message has no price in it."""
    return len(text.split()) <= 6 and "?" not in text and bool(_YES.search(text))


def is_refusal(text: str) -> bool:
    """A short message with a clear no. Plain code. Only used when the message has no price in it."""
    return len(text.split()) <= 25 and bool(_REFUSAL.search(text))


def next_firm_state(
    was_firm: bool, says_firm_now: bool, previous_offer: float | None, new_offer: float | None, pushes: int
) -> tuple[bool, int]:
    """(firm, pushes) after a new vendor message. A vendor who says "final" and later lowers the price is open again."""
    if says_firm_now:
        return True, (pushes if was_firm else 0)
    if was_firm and previous_offer is not None and new_offer is not None and new_offer < previous_offer - SAME_PRICE:
        return False, 0
    return was_firm, pushes


def usable_leverage(best_other: float | None, vendor_offer: float, median: float, ceiling: float) -> float | None:
    """The competing price we may state, or None. Checked again here, whatever the tracker said.
    It must be lower than this vendor's price and not far below the market. It may be above the market or our ceiling: it is a
    price another vendor really gave (a fact), not an offer from us."""
    if best_other is None or best_other >= vendor_offer - SAME_PRICE:
        return None
    if best_other < MIN_CREDIBLE_RATIO * median:
        return None
    return best_other


def compute_counter(
    vendor_offer: float, ceiling: float, median: float, last_counter: float | None, extra_cap: float | None = None
) -> float | None:
    """The next counter price, or None if there is no sensible one.

    reference = the market price (or the ceiling if that is lower): the most the agent offers on its own
    cap       = the reference, and one step below the vendor's price
    first     = 93% of the reference. A real buyer starts below the market, not at it.
    later     = last counter plus 30% of the gap to the cap
    always    = never lower than the last counter, always rounded down
    extra_cap = when another vendor already gave a better price, we never offer more than (that price minus a step)
    """
    ref = reference_price(median, ceiling)
    cap = min(ref, vendor_offer - step_for(vendor_offer))
    if extra_cap is not None:
        cap = min(cap, extra_cap)  # never offer more than the best price we already hold
    if cap <= 0:
        return None
    raw = min(cap, ANCHOR_RATIO * ref) if last_counter is None else min(cap, last_counter + GAP_SHARE * (cap - last_counter))
    counter = floor_price(raw)
    if last_counter is not None:
        counter = max(counter, last_counter)
    counter = min(counter, floor_price(cap))  # rounding can never lift it over the cap
    return counter if counter > 0 else None


# ---------------------------------------------------------------- the decision


def _summary(s: Situation, ceiling: float, target: float | None) -> str:
    m = lambda n: format_price(n, s.currency)
    parts = []
    if s.offers_so_far:
        parts.append(f"Best offer so far: {m(min(s.offers_so_far))}.")
    if s.research_low is not None and s.research_high is not None:
        parts.append(f"Market range: {m(s.research_low)} to {m(s.research_high)}.")
    if target is not None and s.vendor_offer is not None and s.vendor_offer > target:
        parts.append(f"Their price is {m(s.vendor_offer - target)} above your target of {m(target)}.")
    return " ".join(parts)


def _advise_on(s: Situation, ceiling: float, why: str, median: float) -> Recommendation:
    """Advice when we stop for the user. By default "accept" means at or below the MARKET price.
    A price above the market is advised against, even when it is within the maximum. A price above the
    maximum is never recommended for acceptance."""
    assert s.vendor_offer is not None
    m = lambda n: format_price(n, s.currency)
    offer = s.vendor_offer
    limit = min(s.max_price, median) if s.accept_only_below_market else s.max_price
    effective = offer - s.offer_credit  # a good deal is judged after the extras you value, but you can never pay above your maximum
    if effective <= limit and offer <= s.max_price:
        extras = f" (counting the free extras you value, it is {m(effective)})" if s.offer_credit > 0 else ""
        if s.accept_only_below_market:
            return Recommendation("accept", f"{why} Their price of {m(offer)}{extras} is at or below the market price of {m(median)}.".strip())
        return Recommendation("accept", f"{why} Their price of {m(offer)}{extras} is within your maximum of {m(s.max_price)}.".strip())
    if offer > s.max_price * FAR_ABOVE:
        return Recommendation("reject", f"{why} Their price of {m(offer)} is far above your maximum of {m(s.max_price)}.".strip())
    if offer <= s.max_price:
        return Recommendation(
            "counter",
            f"{why} Their price of {m(offer)} is above the market price of {m(median)}, so it is not a good deal yet. "
            f"Try one more counter at or below {m(median)}, or reject. You can still accept it yourself if you want it.".strip(),
        )
    return Recommendation(
        "counter",
        f"{why} Their price of {m(offer)} is above your maximum of {m(s.max_price)}. You could counter, up to {m(ceiling)} without revealing your limit.".strip(),
    )


def decide(s: Situation) -> Decision:
    """The heart of the negotiation. The first rule that applies wins."""
    ceiling = compute_ceiling(s.max_price, s.ceiling_ratio)
    low, med = s.research_low, s.research_median
    target = target_price(low, med, ceiling) if low is not None and med is not None else None
    m = lambda n: format_price(n, s.currency)

    def stop(reason: str, rec: Recommendation | None = None) -> Decision:
        return Decision("needs_you", reason, None, rec, ceiling, target)

    def finish(why: str, rec: Recommendation, stop_reason: str, summary: str) -> Decision:
        """We stop texting this vendor. The chat stays open. If other vendors are still negotiating we wait for
        them ("hold"), because the best price may still come from someone else. Otherwise the user decides."""
        text = f"{why} {summary}".strip()
        if s.others_active:
            return Decision("hold", f"{text} Waiting for the other vendors.", None, rec, ceiling, target, stop_reason=stop_reason)
        return Decision("needs_you", text, None, rec, ceiling, target, stop_reason=stop_reason)

    # 1. A trick: block this vendor and send nothing.
    if s.safety_verdict == "injection":
        return Decision("block", "The message tried to give orders to the agent, so this vendor is blocked.", None, None, ceiling, target)
    if s.safety_needs_user:
        return stop("The safety check wants you to look at this message first.")

    # 1b. The vendor just talked (a question, a complaint, "how is that possible") and gave no price. A person answers what was said and
    #     asks again for a better price. We do NOT send another counter: nothing changed, so a new number would only sound like a robot.
    if s.no_new_price and s.messages_sent > 0 and not s.stopped and s.refusal:
        # A clear "no": do not keep asking. Say we will get back to them, stop texting, and compare all prices. If another vendor later
        # gets a lower price, this vendor is written to again with that price (nobody is dropped for good).
        return Decision("close", "The vendor clearly said no. Say we will get back to them and stop asking.", None, None, ceiling, target, stop_reason="refused")
    if s.no_new_price and s.messages_sent > 0 and s.affirmation and s.vendor_offer is not None and not s.refusal:
        # "yes": the vendor confirms. No new question, no second message. We say once that we will check the market and get back (the
        # manager sends that line), and wait. A lower price from another vendor wakes this vendor up later.
        action = "hold" if s.others_active else "needs_you"
        return Decision(action, "The vendor confirmed with a yes. Nothing new to ask. Waiting for the other vendors.", None, None, ceiling, target, stop_reason="confirmed")
    if s.no_new_price and s.messages_sent > 0 and s.stopped and s.refusal:
        # A "no" after we already said goodbye: nothing more to say (no second goodbye).
        return Decision("hold", "The vendor said no again after our goodbye. Staying quiet.", None, None, ceiling, target)
    if s.no_new_price and s.messages_sent > 0:
        # Also when the Accept box is showing (we stopped texting them): a new vendor message is still answered, and the box goes away
        # because the chat is negotiating again. Only a clear no after the goodbye gets silence.
        # Patience: the first casual message only gets a friendly reply, no price pressure. When the vendor is still chatting on the
        # next message, we answer AND send a second message that goes back to the price (market price, "too high", a competing price).
        if s.upset or s.casual_streak < CASUAL_PATIENCE:
            why = "The vendor sounds upset. Reply kindly and calmly, and do not talk about the price." if s.upset else "The vendor is chatting (no price). Reply like a friendly person and do not push the price yet."
            return Decision("chat", why, None, None, ceiling, target)
        lever = usable_leverage(s.best_other_offer, s.vendor_offer, med, ceiling) if s.vendor_offer is not None and med is not None else None
        return Decision(
            "chat", "The vendor is still chatting. Reply to them, then send a second message that goes back to the price.",
            None, None, ceiling, target, leverage_price=lever, back_to_business=True,
        )  # fmt: skip

    # 2. The vendor has not quoted a price yet: open the conversation (no numbers in this message). This needs no market price, so a
    #    failed research must never stop us from at least asking every vendor for their price.
    if s.vendor_offer is None and not s.offer_parse_failed:
        return Decision("first_message", "The vendor has not quoted a price yet. Ask for their best price.", None, None, ceiling, target)

    # 2b. No trustworthy market price (research failed, or it is low confidence): do NOT stop and hand the chat to the user. The agent
    #     negotiates from what the vendors themselves said: the lowest price on the table is the reference, and the competing price is
    #     still shared. It never states a market price in this mode (the writer gets none). Counters still stop at the ceiling.
    if s.offer_parse_failed:
        return stop("The agent could not read a clear price in the vendor's message, so it needs you.")
    pseudo = s.research_confidence in (None, "low") or low is None or med is None
    pre = ""
    if pseudo:
        assert s.vendor_offer is not None
        med = min(x for x in (s.vendor_offer, s.best_other_offer) if x is not None)
        low = med * PSEUDO_LOW_RATIO
        target = target_price(low, med, ceiling)
        pre = "No trusted market price, so the agent compares the vendors' own prices. "

    offer = s.vendor_offer
    assert offer is not None
    assert target is not None
    summary = _summary(s, ceiling, target)

    firm_used_up = s.firm and s.firm_pushes >= FIRM_PUSH_LIMIT
    lever = usable_leverage(s.best_other_offer, offer, med, ceiling)
    # A vendor who said "final" is told about a LOWER competing price once (new information, and rounds still limit it). Never twice for the same price.
    can_lever = lever is not None and s.rounds < s.max_rounds and lever != s.last_leverage

    def leverage_decision() -> Decision:
        return Decision(
            "leverage", f"{pre}Tell the vendor about the best offer we hold ({m(lever)}) and ask them to beat it.",
            None, None, ceiling, target, leverage_price=lever, firm_push=s.firm,
        )  # fmt: skip

    # 4. Their price is already good enough (after the free extras you value). If another vendor is lower, still ask this one to beat it.
    if offer - s.offer_credit <= target and offer <= s.max_price:
        if can_lever:
            return leverage_decision()
        return finish(
            "Good price reached.", Recommendation("accept", f"{m(offer)} is at or below your target of {m(target)}."), "good_price", summary
        )

    # 4a. The price is already close to the lowest price on the whole market. Asking for $219 when nobody sells below $248 only repeats
    #     the same cycle. We stop pushing. If another vendor holds a lower price we still say so once ("I already have an offer of ..."),
    #     because that is real leverage. The chat stays open, and the final pick is the lowest price among all vendors.
    if offer - s.offer_credit <= low * NEAR_LOW_RATIO:
        if can_lever:
            return leverage_decision()
        why = "The price is already close to the lowest market price."
        return finish(why, _advise_on(s, ceiling, why, med), "near_market_low", summary)

    # 4b. The vendor met our last counter, or is within one step of it. Countering again would only chase ourselves.
    if s.last_counter is not None and offer - s.last_counter < step_for(offer):
        return finish(
            "The vendor is at or very near your last counter.",
            _advise_on(s, ceiling, "The vendor has met your last counter.", med), "met_counter", summary,
        )  # fmt: skip

    # 4c. The vendor says the price is final and we already tried our pushes: stop texting (the chat stays open).
    if firm_used_up:
        if can_lever:  # a LOWER competing price is new information: say it once before saying goodbye
            return leverage_decision()
        why = "The vendor says the price is final and did not move after our extra tries."
        rec = _advise_on(s, ceiling, why, med)
        if s.stopped:  # the goodbye was already sent: stay silent
            return finish(why, rec, "firm_price", summary)
        return Decision("close", f"{why} {summary}".strip(), None, rec, ceiling, target, stop_reason="firm_price")

    # 5. Out of rounds, or the vendor keeps repeating the same price.
    if s.rounds >= s.max_rounds:
        why = f"{s.max_rounds} rounds used."
        return finish(why, _advise_on(s, ceiling, why, med), "round_limit", summary)
    if s.stall_count >= STALL_LIMIT:
        why = "The vendor keeps repeating the same price."
        return finish(why, _advise_on(s, ceiling, why, med), "stalled", summary)

    # 6. Your budget is far below the market price.
    cap = min(reference_price(med, ceiling), offer - step_for(offer))
    if cap < MIN_BUDGET_RATIO * med:
        return stop(
            f"Your budget looks too low for this item. The most the agent may offer is {m(max(cap, 0))}, but the market median is {m(med)}.",
            Recommendation("reject", "The agent cannot make a realistic offer within your limit."),
        )

    # 7. Keep negotiating: the formula picks the counter.
    extra_cap = lever - step_for(lever) if lever is not None else None
    counter = compute_counter(offer, ceiling, med, s.last_counter, extra_cap)
    stuck = counter is None or (s.last_counter is not None and counter <= s.last_counter + SAME_PRICE)
    if stuck and can_lever:
        # Our own counter is already at or above the best offer we hold, so offering a number would be pointless.
        return leverage_decision()
    if counter is None:
        return stop("The agent could not find a sensible counter price, so it needs you.")
    if stuck:
        # We are already at the highest price we may offer. Sending the same counter again would change nothing.
        why = "The agent is already at the most it will offer on its own (the market price)."
        return finish(why, _advise_on(s, ceiling, why, med), "at_limit", summary)
    note = f" {pre}Counter at {m(counter)}."
    if can_lever:
        note += f" Mention the best offer we hold ({m(lever)})."
    if s.firm:
        note += " The vendor said the price is final, so this is one more try."
    return Decision(
        "counter", note.strip(), counter, None, ceiling, target,
        leverage_price=lever if can_lever else None, firm_push=s.firm,
    )  # fmt: skip
