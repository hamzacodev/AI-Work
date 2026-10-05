"""The Negotiator: writes the buyer's message to a vendor. It works for YOU, the buyer.

In easy words: the code has already decided WHAT to do and WHAT PRICE to offer (negotiation/strategy.py).
The Negotiator only finds the right words, like a person writing "Could you do $651?" in a friendly way.

Every draft then has to pass TWO checks before it can be sent:
  1. a number check by code: it must contain the price the code chose (or no price at all for a first message)
  2. the Fact Checker (nothing invented, no unapproved promises) and the Limit Checker (prices, secrets, payments)
If a draft fails, the Negotiator is told exactly what was wrong and writes it again, at most 2 times.
If it still fails, nothing is sent and the user is asked. The AI never sends anything by itself.
"""

import re
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from app.agents.fact_checker import MAX_REWRITES, check_draft
from app.agents.fact_rules import ApprovedFacts, Source, Turn
from app.core.llm import UNTRUSTED_NOTICE, LLMError, llm_label, untrusted
from app.core.money import format_price
from app.guardrails.limit_checker import Context as LimitContext
from app.guardrails.limit_checker import check_outgoing
from app.guardrails.prices import extract_prices, numbers_in
from app.negotiation.addons import words
from app.negotiation.strategy import Decision
from app.negotiation.tactics import Tactics

MAX_WORDS = 70
HISTORY_TURNS = 4  # the writer needs the vendor's last message and our last one, not the whole chat (it was 8)
FACT_CHECK_TURNS = 6  # the Fact Checker verifies "you said ..." claims, so it sees a little more (it was the whole chat)
PRICE_TOLERANCE = 0.01
MAX_SOURCES_NAMED = 2


class Draft(BaseModel):
    message: str


class JsonLLM(Protocol):
    async def complete_json(self, role: str, system: str, user: str, schema: type, deal_id: str | None = None): ...


@dataclass
class NegotiationContext:
    """Everything the Negotiator knows. It is built from the database and the other steps."""

    decision: Decision  # what to do. Must be "first_message", "counter" or "leverage".
    item: str
    currency: str
    max_price: float  # used ONLY by the Limit Checker. It is never put in a prompt.
    recipient: str  # the vendor's contact
    vendor_contacts: frozenset[str]
    conversation: list[Turn] = field(default_factory=list)
    must_haves: list[str] = field(default_factory=list)
    vendor_offer: float | None = None
    vendor_prices: tuple[float, ...] = ()
    previous_counter: float | None = None
    rounds: int = 0  # counters already sent to this vendor
    max_rounds: int = 3
    ceiling_ratio: float = 0.95
    research_low: float | None = None
    research_median: float | None = None
    research_high: float | None = None
    sources: list[Source] = field(default_factory=list)
    tactics: Tactics = field(default_factory=Tactics)
    keep_addons: list[str] = field(default_factory=list)  # free extras you value that the vendor gives only from a higher price
    address: str = ""  # private. Kept only so the Limit Checker can make sure it never leaks.
    phone: str | None = None


@dataclass
class NegotiatorResult:
    ok: bool
    message: str | None = None
    needs_user: bool = False
    rewrites: int = 0
    problems: list[str] = field(default_factory=list)
    followup: str | None = None  # a second message to send right after `message` (chat, back to business)


# ---------------------------------------------------------------- the prompt


def leverage_sentence(c: NegotiationContext) -> str | None:
    """The exact sentence that tells the vendor about the best offer we hold. Built by code from a real number.
    It never says who gave it. (It is trusted word for word by the Fact Checker, like the tactic sentences.)"""
    price = c.decision.leverage_price
    return f"I already have an offer of {format_price(price, c.currency)} for this item." if price is not None else None


def keep_sentence(c: NegotiationContext) -> str | None:
    """"Could you keep the free charger at that price?" Built by code from the closed add-on list."""
    return f"Could you keep the free {words(c.keep_addons)} at that price?" if c.keep_addons and c.decision.action == "counter" else None


def _opening(text: str) -> str:
    """The first four words, lower case: how a message starts."""
    return " ".join(re.findall(r"[a-z0-9$']+", text.lower())[:4])


def _recent_openings(c: NegotiationContext) -> list[str]:
    sent = [_opening(t.text) for t in c.conversation if t.sender == "agent"][-10:]  # a chat has at most 10 rounds: look at all of it
    return [o for o in sent if len(o.split()) >= 3]


def _repeated_opening(draft: str, c: NegotiationContext) -> list[str]:
    """A message that starts the same way as one we already sent in this chat sounds like a robot (the judge counted "I see you have lowered the
    price" 36 times in 8 deals). The writer is asked to rewrite it. The plain fallback templates are exempt, so this never stops the agent."""
    if c.decision.action in ("first_message", "close"):
        return []
    mine = _opening(draft)
    return [f'You already started a message with "{mine}". Start this one differently and keep it short.'] if mine in _recent_openings(c) else []


def _vary_rule(c: NegotiationContext) -> str:
    seen = _recent_openings(c)
    if not seen:
        return ""
    return "Vary your wording. Your earlier messages started with: " + "; ".join(f'"{s}"' for s in seen) + ". Do not start this message the same way, and do not repeat your earlier sentences."


def _market_argument_allowed(c: NegotiationContext) -> bool:
    """The market price is an argument only when the vendor asks MORE than it. If their price is already at or below the market, quoting
    the market price would argue against the buyer (found in a live test: "you said $1,500, similar listings are around $1,539")."""
    return c.research_median is not None and (c.vendor_offer is None or c.vendor_offer > c.research_median)


def _known_details(c: NegotiationContext) -> str:
    """The only product facts the writer has. Asked for more (model, year, size, color), it must not guess."""
    known = "; ".join([c.item, *c.must_haves])
    return (
        f"The ONLY facts you know about what the buyer wants are: {known}. If the vendor asks about a detail that is not in that list "
        "(model, year, size, color, storage), do NOT guess or invent one: say you will check with the buyer."
    )


def _system_prompt(c: NegotiationContext) -> str:
    m = lambda n: format_price(n, c.currency)
    rules = [
        f"Write ONE short message (at most {MAX_WORDS} words, 1 to 3 sentences) from a BUYER to a vendor about: {c.item}.",
        "Be polite, warm and direct, like a real person on WhatsApp or email. Plain text only. No subject line, no signature, no placeholders.",
        "Never reveal how much the buyer can pay, never give an address or phone number, never accept a deal. Do not mention payment, cash on delivery or delivery at all.",
        "Never mention other sellers, other offers, friends or reviews unless a line below allows it. Never invent anything.",
    ]
    if c.decision.action == "first_message":
        rules.append("This is the FIRST message. Say you are interested and ask for their best price. Do NOT write any price or number.")
    elif c.decision.action == "chat":
        rules.append(
            "The vendor's last message has NO price in it. It is small talk or a question. Reply to exactly what they said, like a friendly "
            "real person chatting on WhatsApp: answer briefly and honestly, be warm, and if it feels natural ask one light question back. "
            "You cannot look things up (weather, news), so if asked, say you do not know where they are and ask about their side. "
            "If they are unkind or upset (for example they say they do not like you), stay calm and warm, apologise briefly if it fits, and do not mention the item or the price at all. "
            "If they sound surprised or unhappy, be kind. Do NOT ask for a price or a discount in this message and do not push the deal: "
            "just be patient and human. Never ask the vendor new questions about the product (colors, specs, delivery, meeting times). Do NOT write any price or any number. Do not use stiff phrases like 'Thank you for confirming'. "
            + _known_details(c)
        )
    elif c.decision.action == "leverage":
        sentence = leverage_sentence(c)
        assert sentence is not None
        rules.append(
            f'Include exactly this sentence once, word for word: "{sentence}" Then ask politely whether they can do better than that. '
            "Do not write any other price. Do not say who made the other offer."
        )
        if c.vendor_offer is not None:
            rules.append(f"You may mention the vendor's own price ({m(c.vendor_offer)}) in a few words.")
    else:
        assert c.decision.counter_price is not None
        rules.append(
            f"Make a counter offer of exactly {m(c.decision.counter_price)}. Write that price once, as a question such as "
            f'"Could you do {m(c.decision.counter_price)}?". Do not write any other price except what is allowed below.'
        )
        last_round = c.rounds >= c.max_rounds - 1
        if _market_argument_allowed(c) and (c.rounds == 0 or last_round):
            # The market-price argument is used in the first and the last round only. Repeating it every round sounds like a robot.
            named = ", ".join(s.title for s in c.sources[:MAX_SOURCES_NAMED])
            rules.append(
                f'You may justify your offer with exactly this sentence: "Similar listings are around {m(c.research_median)}'
                f'{f" ({named})" if named else ""}." Use it once, and do not name any other source.'
            )
        elif c.rounds > 0:
            rules.append("Do NOT repeat the market-price argument you used before. Briefly acknowledge the vendor's new, lower price instead.")
        if c.vendor_offer is not None:
            if c.rounds == 0:
                rules.append(f"You may mention the vendor's own price ({m(c.vendor_offer)}) when you reply to it.")
            else:
                rules.append(f"You may mention the vendor's new price ({m(c.vendor_offer)}) in a few words, for example that you see they have lowered it.")
    if c.decision.action == "counter" and c.decision.leverage_price is not None:
        rules.append(
            f'Also include exactly this sentence once, word for word: "{leverage_sentence(c)}" Do not say who made the other offer.'
        )
    if keep_sentence(c):
        rules.append(f'Also include exactly this sentence once, word for word: "{keep_sentence(c)}"')
    if c.decision.firm_push:
        rules.append(
            "The vendor said their price is final. Acknowledge that politely in a few words, then try once more. Do not argue or complain."
        )
    if c.decision.action == "counter":
        required = c.tactics.required_sentences(c.rounds, _said(c))
        if required:
            listed = " ".join(f'"{x}"' for x in required)
            rules.append(
                "Include exactly these sentences once each, word for word. They give the vendor a reason to lower the price: " + listed
            )
    if _vary_rule(c) and c.decision.action != "first_message":
        rules.append(_vary_rule(c))
    rules.append(UNTRUSTED_NOTICE)
    if c.decision.action == "chat":
        examples = 'Example of a reply: "I am good, thanks! I cannot see the weather from here, but I hope it is nice where you are. How is your day going?"'
    elif c.decision.action == "counter" and c.rounds > 0:
        # Later rounds get a different example, so the model does not copy the first-round wording again.
        examples = f'Example of a counter: "I see you have lowered the price, thank you. Could you do {m(c.decision.counter_price or 0)}?"'
    else:
        examples = (
            'Example of a counter: "Thank you for the quick reply. Similar listings are around $700 (Retailer A), so I was hoping '
            'you could do better. Could you do $651?"\n'
            'Example of a first message: "Hello, I am interested in the Dell XPS 15 with 16GB RAM. What is your best price?"'
        )
    return "\n".join(f"- {r}" if not r.startswith("  ") else r for r in rules) + "\n\n" + examples


def _conversation_text(c: NegotiationContext) -> str:
    names = {"vendor": "VENDOR", "agent": "BUYER (you)", "owner": "BUYER"}
    if not c.conversation:
        return "(no messages yet)"
    return "\n".join(f"{names[t.sender]}: {t.text}" for t in c.conversation[-HISTORY_TURNS:])


def _user_prompt(c: NegotiationContext, previous: str | None, feedback: str | None) -> str:
    parts = [
        "CONVERSATION SO FAR:\n" + untrusted("conversation", _conversation_text(c)),
        f"Required features: {', '.join(c.must_haves) or 'none'}.",
    ]
    if previous and feedback:
        parts.append(
            "YOUR PREVIOUS DRAFT WAS REJECTED. Do not repeat it.\n"
            f"Previous draft: {previous}\nWhy it was rejected:\n{feedback}\nWrite a new, corrected message."
        )
    parts.append('Answer with JSON: {"message": "<the message>"}')
    return "\n\n".join(parts)


# ---------------------------------------------------------------- the checks around a draft


def check_numbers(draft: str, c: NegotiationContext) -> list[str]:
    """The number check by code. A counter must contain the chosen price. A first message must contain no price."""
    known = numbers_in(" ".join([c.item, *c.must_haves]))
    prices = extract_prices(draft, known)
    if c.decision.action in ("first_message", "chat", "close"):
        what = "first message" if c.decision.action == "first_message" else "reply"
        problems = [f"The {what} must not contain any price, but it contains '{p.raw}'." for p in prices[:1]]
        if c.decision.action == "chat":
            problems += _invented_numbers(draft, c)
        return problems
    problems = []
    if re.search(r"similar listings|market price|the market is", draft, re.IGNORECASE) and not _market_argument_allowed(c):
        problems.append("Do not quote the market price: the vendor's price is already at or below it.")
    sentence = leverage_sentence(c)
    if sentence is not None and _squash(sentence) not in _squash(draft):
        problems.append(f'The message must include this sentence exactly: "{sentence}"')
    keep = keep_sentence(c)
    if keep is not None and _squash(keep) not in _squash(draft):
        problems.append(f'The message must include this sentence exactly: "{keep}"')
    if c.decision.action == "leverage":
        return problems
    target = c.decision.counter_price
    assert target is not None
    if not any(abs(p.value - target) <= PRICE_TOLERANCE for p in prices):
        problems.append(f"The message must contain the counter price {format_price(target, c.currency)} exactly.")
    for required in c.tactics.required_sentences(c.rounds, _said(c)):
        if _squash(required) not in _squash(draft):
            problems.append(f'The message must include this sentence exactly: "{required}"')
    return problems


_DIGITS = re.compile(r"\d+")


def _invented_numbers(draft: str, c: NegotiationContext) -> list[str]:
    """A chat reply may only use numbers that are already in the item, the must-haves or the chat. This stops "the 13-inch M2 model"
    when the buyer never said so (found in a live test)."""
    known = set(_DIGITS.findall(" ".join([c.item, *c.must_haves, *(t.text for t in c.conversation)])))
    new = [d for d in _DIGITS.findall(draft) if d not in known]
    return [f"The reply uses the number '{new[0]}', which is not in the buyer's request or the chat. Do not invent product details."] if new else []


def _said(c: NegotiationContext) -> tuple[str, ...]:
    """What the agent already wrote to this vendor, so the tactic lines are not repeated."""
    return tuple(t.text for t in c.conversation if t.sender == "agent")


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def facts_for(c: NegotiationContext) -> ApprovedFacts:
    t = c.tactics
    return ApprovedFacts(
        item=c.item,
        must_haves=c.must_haves,
        currency=c.currency,
        counter_price=c.decision.counter_price,
        vendor_prices=list(c.vendor_prices) + ([c.vendor_offer] if c.vendor_offer is not None else []),
        research_low=c.research_low,
        research_median=c.research_median,
        research_high=c.research_high,
        sources=c.sources,
        conversation=c.conversation[-FACT_CHECK_TURNS:],
        may_buy_quantity=t.may_buy_quantity,
        may_buy_again=t.may_buy_again,
        may_refer=t.may_refer,
        approved_notes=t.approved_notes(),
        approved_sentences=t.persuasion_lines()
        + [x for x in (leverage_sentence(c), keep_sentence(c)) if x],
    )


def limit_context_for(c: NegotiationContext) -> LimitContext:
    research = tuple(v for v in (c.research_low, c.research_median, c.research_high) if v is not None)
    return LimitContext(
        max_price=c.max_price,
        recipient=c.recipient,
        vendor_contacts=c.vendor_contacts,
        ceiling_ratio=c.ceiling_ratio,
        counter_price=c.decision.counter_price,
        competing_offer=c.decision.leverage_price,
        previous_counter=c.previous_counter,
        vendor_offer=c.vendor_offer,
        vendor_prices=c.vendor_prices,
        research_figures=research,
        known_numbers=numbers_in(" ".join([c.item, *c.must_haves])),
        address=c.address,
        phone=c.phone,
        phase="negotiating",
        rounds=c.rounds + (1 if c.decision.action in ("counter", "leverage") else 0),
        max_rounds=c.max_rounds,
    )


# ---------------------------------------------------------------- the whole job


async def write_draft(c: NegotiationContext, llm: JsonLLM, previous: str | None, feedback: str | None, deal_id: str | None) -> str:
    with llm_label("Negotiator", f"write a {c.decision.action} message", history=_conversation_text(c)):
        out = await llm.complete_json("main", _system_prompt(c), _user_prompt(c, previous, feedback), Draft, deal_id)
    return " ".join(out.message.split())  # tidy whitespace


def first_message_text(c: NegotiationContext) -> str:
    """The first message to a vendor is always the same simple question, so it is a fixed template: instant, and no model call
    that could go wrong or take a minute on a laptop. It contains only the item and the must-haves you typed, and no price."""
    must = f" with {', '.join(c.must_haves)}" if c.must_haves else ""
    return f"Hello, I am interested in the {c.item}{must}. What is your best price?"


# Said when a vendor's price is already good and we stop. Not an acceptance (only the buyer accepts), and no numbers (nothing to leak or invent).
# It says it will check the market and get back; a lower price from another vendor later wakes this vendor up ("I already have an offer of ...").
ACK_TEXT = "Thank you, that price is noted. Let me check the market and my other options, and I will get back to you shortly."
CLOSE_TEXT = "Okay, understood, thank you. I will check my other options and get back to you."
CHAT_FALLBACK_ITEM = "Good question, I will check the exact details with my buyer. Meanwhile, which models do you have available?"
CHAT_FALLBACK = "Thanks for the reply, I am doing well. How is your day going?"


def business_text(c: NegotiationContext) -> str:
    """The plain fallback for the second message of a casual exchange (the model writes it first, see `_write_business`). Fixed words,
    every number from code. It says "too high" only when the vendor's price really is above the market."""
    m = lambda n: format_price(n, c.currency)
    offer, med = c.vendor_offer, c.research_median
    odd = len(c.conversation) % 2 == 1
    if offer is None:
        text = "By the way, what is the best price you can do on it?" if odd else "Anyway, nice talking to you. What is the best price you can give me?"
    elif med is not None and offer > med:
        text = (
            f"Anyway, about the price: {m(offer)} feels a bit high to me, similar listings are around {m(med)}. Is there any room to come down? That is why I came to you."
            if odd
            else f"By the way, {m(offer)} is a bit more than I am seeing elsewhere, around {m(med)}. Could you do something about it? I came to you hoping you would give me a better price."
        )
    else:
        text = f"Anyway, back to the price: could you do a little better than {m(offer)}?"
    lever = leverage_sentence(c)
    if lever:
        text += f" {lever} I came to you because I think you can give me a better price than that seller. Can you beat it?"
    return text


def _business_prompt(c: NegotiationContext) -> str:
    m = lambda n: format_price(n, c.currency)
    facts = []
    if c.vendor_offer is not None:
        facts.append(f"The vendor's price is {m(c.vendor_offer)}.")
        if c.research_median is not None and c.vendor_offer > c.research_median:
            facts.append(f"That is above the market price, which is around {m(c.research_median)}. You may say it feels high.")
        elif c.research_median is not None:
            facts.append(f"The market price is around {m(c.research_median)}.")
    if c.decision.leverage_price is not None:
        facts.append(
            f"Another seller offered {m(c.decision.leverage_price)}. Say you already have another offer at that price (never a name), and that you "
            "came to this vendor hoping they could give a better price than that seller."
        )
    if not facts:
        facts.append("No price has been mentioned yet, so ask for their best price. Do not write any number.")
    return (
        f"Write ONE short WhatsApp message (1 or 2 sentences, at most 45 words) from a BUYER to a vendor about: {c.item}. The chat so far was friendly "
        "small talk. Now gently steer the talk back to the price, the way a warm, real person would, for example with 'anyway' or 'by the way'. "
        "Do not sound like a form or a salesperson, and do not use phrases like 'back to business'. Plain text only. "
        "You may use ONLY these facts, and you must write each price exactly as shown: " + " ".join(facts)
        + " Never reveal how much the buyer can pay, never give an address or phone number, never accept a deal, never invent anything. "
        + UNTRUSTED_NOTICE
    )


async def _write_business(c: NegotiationContext, llm: JsonLLM, deal_id: str | None) -> str | None:
    """The second message, written by the model from the allowed facts and checked by code (every price must be a known one, the
    competing price must be in it when there is one, and the usual limit checks). Two tries, then None (the plain template is used)."""
    lever = c.decision.leverage_price
    for _ in range(2):
        try:
            with llm_label("Negotiator", "write the way back to the price", history=_conversation_text(c)):
                out = await llm.complete_json("main", _business_prompt(c), _user_prompt(c, None, None), Draft, deal_id)
        except LLMError:
            return None
        text = " ".join(out.message.split())
        if not text or len(text.split()) > MAX_WORDS:
            continue
        if lever is not None and not any(abs(p.value - lever) <= PRICE_TOLERANCE for p in extract_prices(text, numbers_in(" ".join([c.item, *c.must_haves])))):
            continue
        if _business_ok(text, c) and _steers_to_price(text) and "back to business" not in text.lower():
            return text
    return None


_PRICEY = re.compile(r"\b(price|prices|cost|offer|discount|deal|lower|cheaper|better|room|listings)\b", re.IGNORECASE)


def _steers_to_price(text: str) -> bool:
    """The second message must really be about the price, not more small talk."""
    return bool(_PRICEY.search(text))


def _business_ok(text: str, c: NegotiationContext) -> bool:
    """The same plain-code checks as any message, plus: every price in it must be one the code knows."""
    known = numbers_in(" ".join([c.item, *c.must_haves]))
    allowed = [x for x in (c.vendor_offer, c.research_median, c.decision.leverage_price) if x is not None]
    prices = extract_prices(text, known)
    if any(not any(abs(p.value - a) <= PRICE_TOLERANCE for a in allowed) for p in prices):
        return False
    return check_outgoing(text, limit_context_for(c)).allowed


def fallback_text(c: NegotiationContext) -> str | None:
    """A plain template for when the model cannot write a message that passes the checks (it wrote a wrong number, or the model was down).
    Every number comes from code. The agent keeps talking instead of stopping and handing the chat to you. It still goes through the same checks."""
    d = c.decision
    if d.action == "chat":
        last = next((t.text.lower() for t in reversed(c.conversation) if t.sender == "vendor"), "")
        about_item = "?" in last and not re.search(r"how are|how r u|weather|what about you|how.s your|how is your", last)
        return CHAT_FALLBACK_ITEM if about_item else CHAT_FALLBACK
    parts = []
    if d.action == "counter" and d.counter_price is not None:
        parts.append(f"Thank you. Could you do {format_price(d.counter_price, c.currency)}?")
    elif d.action == "leverage":
        parts.append("Thank you.")
    else:
        return None
    for extra in (leverage_sentence(c), keep_sentence(c)):
        if extra:
            parts.append(extra)
    if d.action == "counter":
        parts += c.tactics.required_sentences(c.rounds, _said(c))  # the sentences the buyer's tactics settings require, word for word
    if d.action == "leverage":
        parts.append("Can you beat that price?")
    return " ".join(parts)


def _fallback_result(c: NegotiationContext, attempts: int, problems: list[str]) -> NegotiatorResult:
    text = fallback_text(c)
    if text and not check_numbers(text, c) and check_outgoing(text, limit_context_for(c)).allowed:
        return NegotiatorResult(True, text, False, attempts)
    return NegotiatorResult(False, None, True, attempts, problems)


async def negotiate(c: NegotiationContext, llm: JsonLLM, deal_id: str | None = None) -> NegotiatorResult:
    """Writes the message. After a casual exchange (`back_to_business`) a second, fixed message goes with it: back to the price."""
    result = await _negotiate_one(c, llm, deal_id)
    if result.ok and c.decision.action == "chat" and c.decision.back_to_business:
        text = await _write_business(c, llm, deal_id)
        if text is None:
            text = business_text(c)
            if not _business_ok(text, c):
                return result
        result.followup = text
    return result


async def _negotiate_one(c: NegotiationContext, llm: JsonLLM, deal_id: str | None = None) -> NegotiatorResult:
    """Writes a message and makes sure it is safe. Returns ok=True with the message, or needs_user=True with the reasons."""
    if c.decision.action not in ("first_message", "counter", "leverage", "chat", "close"):
        raise ValueError(f"The Negotiator only writes messages. It cannot handle the action '{c.decision.action}'.")

    if c.decision.action == "close":
        # A fixed, polite goodbye: no model call, no number. It still goes through the plain-code checks.
        if not check_numbers(CLOSE_TEXT, c) and check_outgoing(CLOSE_TEXT, limit_context_for(c)).allowed:
            return NegotiatorResult(True, CLOSE_TEXT, False, 0)
        return NegotiatorResult(False, None, True, 0, ["The goodbye message did not pass the checks."])

    if c.decision.action == "first_message":
        text = first_message_text(c)
        # The template still goes through the plain-code checks (no price, nothing private, only vendors on the list).
        if not check_numbers(text, c) and check_outgoing(text, limit_context_for(c)).allowed:
            return NegotiatorResult(True, text, False, 0)

    facts, limit = facts_for(c), limit_context_for(c)
    previous = feedback = None
    problems: list[str] = []

    for attempt in range(MAX_REWRITES + 1):
        try:
            draft = await write_draft(c, llm, previous, feedback, deal_id)
        except LLMError as e:
            return _fallback_result(c, attempt, [f"The agent could not write a message ({type(e).__name__})."])

        problems = []
        if not draft or len(draft.split()) > MAX_WORDS * 2:
            problems.append("The message is empty or far too long. Write 1 to 3 short sentences.")
        problems += check_numbers(draft, c)
        problems += _repeated_opening(draft, c)
        # The Limit Checker is plain code and free. Its result is computed first and handed to the Fact Checker, which stops before
        # its model call if the limits already fail: a draft that must be rewritten anyway never costs a model call.
        violations = check_outgoing(draft, limit).violations if draft else []

        if not problems:
            fact = await check_draft(draft, facts, llm, deal_id, precheck=lambda v=violations: v)  # type: ignore[arg-type]
            if not fact.approved:
                if fact.needs_user:  # the check itself could not run, so a rewrite cannot help
                    return _fallback_result(c, attempt, [p.text for p in fact.problems])
                problems += [p.text for p in fact.problems]
            else:
                problems += violations  # approved without a model call (nothing to check), but the limits must still pass

        if not problems:
            return NegotiatorResult(True, draft, False, attempt)
        previous, feedback = draft, "\n".join(f"- {p}" for p in problems)

    return _fallback_result(c, MAX_REWRITES, problems)
