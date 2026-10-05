"""Layer 1 of the Fact Checker: rules that read OUR draft reply before it is sent.

The Negotiator (an AI) writes drafts. An AI that wants to sound persuasive invents
things: other offers, discounts, promises. These rules catch the common lies. Plain
Python, no AI.

A rule is either:
    block   the draft cannot be sent as written (it is sent back for a rewrite)
    verify  a claim the rules cannot judge alone. It is handed to the model to check.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from app.guardrails.prices import extract_prices, numbers_in

MAX_DRAFT_CHARS = 1500
PRICE_TOLERANCE = 0.01
RESEARCH_TOLERANCE = 1.0


class Source(BaseModel):
    title: str
    url: str = ""


class Turn(BaseModel):
    sender: Literal["vendor", "agent", "owner"]
    text: str
    simulated: bool = False  # true when a fake vendor wrote it (CLAUDE.md: every simulated message is marked)


class ApprovedFacts(BaseModel):
    """The ONLY things the draft may state. Everything else is invented."""

    item: str
    must_haves: list[str] = []
    currency: str = "USD"
    counter_price: float | None = None
    vendor_prices: list[float] = []
    research_low: float | None = None
    research_median: float | None = None
    research_high: float | None = None
    sources: list[Source] = []
    conversation: list[Turn] = []
    phase: Literal["negotiating", "closing"] = "negotiating"  # after the user accepts, the agent may confirm the deal
    # Tactics the buyer approved as TRUE for this deal (see app/negotiation/tactics.py). Off by default.
    may_buy_quantity: int = 1
    may_buy_again: bool = False
    may_refer: bool = False
    approved_notes: list[str] = []  # the same, in words, for the model's list of approved facts
    approved_sentences: list[str] = []  # exact sentences the buyer approved. They are trusted word for word.


@dataclass(frozen=True)
class Finding:
    rule_id: str
    kind: Literal["block", "verify"]
    reason: str
    quote: str = ""


@dataclass(frozen=True)
class Rule:
    id: str
    reason: str
    pattern: re.Pattern[str]
    kind: Literal["block", "verify"] = "block"
    only_negotiating: bool = False  # not applied in the closing phase


def _r(rid, reason, pattern, kind="block", only_negotiating=False) -> Rule:
    return Rule(rid, reason, re.compile(pattern, re.IGNORECASE | re.DOTALL), kind, only_negotiating)


_PLACE = r"(?:shop|store|seller|vendor|dealer|supplier|retailer|buyer|company|website|site|marketplace)"
_PROMISE_VERBS = r"(?:order|buy|purchase|take|commit|place|sign|recommend|review|leave|write|post|refer|promote|bring|come|visit|collect|pick)"

RULES: list[Rule] = [
    # ---- invented competing offers
    _r("competing_offer", "mentions an offer from another seller that we do not have",
       rf"\b(?:another|other|a\s+different|different|competing)\s+{_PLACE}s?\b.{{0,40}}\b(?:offer\w*|quot\w*|sell\w*|has|have|had|giv\w*|charg\w*|price\w*|list\w*|ask\w*|is|are|told|said|would|will|can|could)\b"),
    _r("found_cheaper", "claims to have found a cheaper price or offer elsewhere",
       r"\b(?:i|we)\s+(?:found|saw|got|received|have|was\s+given|were\s+given|was\s+offered|were\s+offered|can\s+get|could\s+get|have\s+seen)\b.{0,50}\b(?:cheaper|lower|better|less|offer|quote|deal)\b"),
    _r("cheaper_elsewhere", "says it is cheaper elsewhere",
       r"\b(?:cheaper|lower|better)\s+(?:price|offer|deal|quote|rate)s?\s+(?:elsewhere|online|nearby|from\s+(?:another|other)|at\s+(?:another|other))\b|\b(?:cheaper|less)\s+(?:elsewhere|online|nearby|down\s+the\s+road|across\s+the\s+road)\b"),
    _r("competitor", "mentions a competitor", r"\bcompetitor|\bcompetition\b"),
    _r("match_their_offer", "asks to match an offer we do not have",
       r"\b(?:match|beat)\s+(?:their|another|that|the\s+other)\s+(?:offer|price|quote)\b"),
    _r("friend_found", "claims a friend or acquaintance got a better deal",
       r"\b(?:a\s+)?(?:friend|colleague|relative|cousin|neighbou?r|brother|sister|someone)\b.{0,40}\b(?:bought|got|paid|found|picked\s+up|purchased)\b"),
    # ---- invented discounts and status
    _r("invented_discount", "claims a discount, coupon or membership that we do not have",
       r"\b(?:i|we)\s+(?:have|got|received|hold|am\s+eligible\s+for|are\s+eligible\s+for|can\s+use|will\s+use)\s+(?:a|an|the|my|our)?\s*(?:discount|coupon|voucher|promo\w*|rebate|cashback|referral|membership|loyalty|student|corporate)\b"),
    _r("discount_type", "mentions a special discount type",
       r"\b(?:student|corporate|military|government|staff|employee|loyalty|member(?:ship)?|wholesale|trade|dealer)\s+(?:discount|price|rate|pricing|card)\b|\bpromo\s*code\b"),
    _r("loyal_customer", "claims to be a returning customer",
       r"\b(?:as|being)\s+(?:a|an)\s+(?:loyal|returning|regular|repeat|valued|existing|previous)\s+(?:customer|client|buyer)\b|\bi\s+(?:bought|ordered)\s+from\s+you\b"),
    _r("you_promised_discount", "claims the vendor already offered a discount",
       r"\byou\s+(?:promised|offered|agreed|gave|already\s+(?:offered|agreed|gave))\b.{0,30}\b(?:discount|free|lower|reduc\w*)\b"),
    # ---- promises we are not allowed to make
    _r("will_commit", "promises an action (buy, review, recommend...)",
       rf"\b(?:i|we)(?:\s+will|'ll|\s+shall|\s+am\s+going\s+to|\s+are\s+going\s+to)\s+(?:definitely\s+|certainly\s+|surely\s+|gladly\s+)?(?:{_PROMISE_VERBS}|pay(?!\s+(?:in\s+)?(?:cash\b|on\s+delivery)))\b"),
    _r("bulk_order", "promises a bulk or larger order",
       r"\bbulk\s+(?:order|purchase|buy|deal)\b|\bin\s+bulk\b|\b(?:order|buy|purchase)\s+(?:\d+|two|three|four|five|six|seven|eight|nine|ten|multiple|several|more|many|a\s+few|extra)\s+(?:units?|pieces?|laptops?|items?|more)\b"),
    _r("repeat_business", "promises future business",
       r"\b(?:repeat|future|more|regular|ongoing)\s+(?:business|orders?|purchases?|customers?)\b|\blong[-\s]?term\s+(?:relationship|partnership|contract|deal|customer|business)\b|\bsee\s+us\s+again\b"),
    _r("contract", "mentions a contract or agreement",
       r"\bcontract\b|\b(?:sign\w*|enter\w*|draw\w*|prepar\w*)\b.{0,25}\b(?:agreement|mou)\b"),
    _r("review_promise", "promises a review or rating",
       r"\b(?:5|five)[-\s]?star\b|\b(?:good|great|positive|glowing|excellent)\s+review\b|\bleave\s+(?:a\s+)?(?:\w+\s+)?review\b|\bwrite\s+(?:a\s+)?(?:\w+\s+)?review\b|\brate\s+you\b|\btestimonial\b"),
    _r("referral_promise", "promises a referral or recommendation",
       r"\brefer\s+(?:you|friends|others|people|customers)\b|\brecommend\s+you\b|\btell\s+(?:my|our)\s+(?:friends|colleagues|family)\b|\bword\s+of\s+mouth\b"),
    _r("guarantee", "makes a guarantee or a promise",
       r"\b(?:i|we)\s+(?:promise|guarantee|assure|swear)\b|\bguarantee\s+(?:you|that)\b"),
    _r("ready_to_buy", "says we are ready to buy or pay now",
       r"\b(?:ready|prepared|willing)\s+to\s+(?:buy|purchase|order|pay|close|finali[sz]e|proceed|commit|confirm)\b|\b(?:i|we)(?:'ll|\s+will)\s+take\s+(?:it|this|them)\b|\bpay\s+(?:today|now|immediately|right\s+away|tomorrow)\b|\bbuy\s+(?:today|now|immediately|right\s+away)\b|\b(?:we|i)\s+can\s+(?:buy|order|purchase)\s+(?:today|now|immediately|right\s+away)\b|\bmoney\s+(?:is\s+)?ready\b|\bcash\s+(?:is\s+)?ready\b", only_negotiating=True),
    _r("accepts_deal", "accepts the deal (only the user may accept)",
       r"\b(?:we|i)\s+accept\b(?!\s+(?:cash|only|payment|cod))|\b(?:we|i)\s+agree\s+to\b(?!\s+(?:cash|pay|only))|\b(?:we|i)\s+approve\b|\bdeal(?:!|\s+done|\s+is\s+done|\s+accepted)|\b(?:it'?s|that'?s|consider\s+it)\s+(?:a\s+)?(?:deal|done|sold|settled)\b|\bwe\s+have\s+a\s+deal\b|\bagreed\b|\bsold\b", only_negotiating=True),
    # ---- threats, identity, history we do not have
    _r("threat", "contains a threat or pressure we are not allowed to use",
       r"\b(?:report\s+you|sue\b|expose\b|blacklist|file\s+a\s+complaint|legal\s+action|lawyer|attorney|police|consumer\s+court|bad\s+review|negative\s+review|warn\s+(?:others|people|customers))"),
    _r("invented_identity", "invents who we are",
       r"\bmy\s+name\s+is\b|\bthis\s+is\s+(?:mr|mrs|ms|dr|mister)\b|\b(?:i|we)\s+(?:am|are)\s+(?:a|an|the)\s+(?:dealer|reseller|business|company|shop\s*owner|wholesaler|retailer|student|doctor|engineer|lawyer|manager|journalist|reviewer|influencer)\b|\b(?:i|we)\s+(?:am|are)\s+buying\s+for\s+(?:my|our|a)\s+(?:company|business|boss|father|mother|client|office|school|team|brother|friend)\b|\bi\s+(?:am|'m)\s+(?:a\s+)?(?:real\s+)?(?:human|person)\b|\bi\s+work\s+(?:at|for|in)\b"),
    _r("invented_history", "claims something we did before",
       r"\b(?:i|we)\s+(?:already|have\s+already|previously)\s+(?:paid|ordered|bought|sent|transferred|booked|reserved|visited|called|messaged)\b|\blast\s+(?:time|week|month|year)\b.{0,25}\b(?:bought|ordered|purchased|paid|visited)\b"),
    # ---- claims about the vendor: the model must check them against the conversation
    _r("vendor_claim", "says what the vendor said or promised",
       r"\byou\s+(?:said|told|mentioned|promised|offered|confirmed|agreed|stated|quoted|guaranteed|assured|wrote|claimed|advertised|listed|have|include|provide|offer)\b|\byour\s+(?:shop|store|reviews?|rating|reputation|product|laptop|item|warranty|delivery)\b", "verify"),
    # ---- the buyer's limit is private, whatever number is mentioned. (The Limit Checker reads numbers. If the vendor
    # ---- happens to quote the same number as the buyer's maximum, only these words can catch "my budget is $800".)
    _r("reveals_budget", "reveals what the buyer can pay",
       r"\b(?:my|our|the\s+buyer'?s?)\s+(?:budget|maximum|max(?:imum)?\s+price|limit|ceiling|top\s+price|walk[-\s]?away)\b"
       r"|\b(?:i|we)\s+(?:can|could|am\s+able\s+to|are\s+able\s+to|will)\s+(?:only\s+)?(?:pay|spend|go|afford)\s+(?:up\s+to|at\s+most|no\s+more\s+than|a\s+maximum\s+of|max)\b"
       r"|\b(?:can'?t|cannot|won'?t|will\s+not|not)\s+(?:go|pay|spend|afford)\s+(?:any\s+)?(?:more|above|over|higher|beyond)\b"
       r"|\bup\s+to\s+(?:[$£€]|usd|pkr|aed)\s*\d|\bat\s+most\s+(?:[$£€]|usd|pkr|aed)\s*\d|\bno\s+more\s+than\s+(?:[$£€]|usd|pkr|aed)\s*\d"),
    # ---- draft quality
    _r("template_leftover", "contains placeholder text",
       r"\[[^\]]{2,30}\]|\{[a-z_ ]{2,30}\}|<[a-z_ ]{2,30}>|\binsert\b.{0,20}\bhere\b|lorem\s+ipsum|\bxxx+\b"),
    _r("ai_leak", "sounds like an AI refusal or disclaimer",
       r"\bas\s+an\s+ai\b|\blanguage\s+model\b|\bi\s+(?:cannot|can't|can\s+not)\s+(?:assist|help|comply|do\s+that)\b|\bi'?m\s+sorry,?\s+but\b|\bi\s+apologi[sz]e,?\s+but\b"),
    _r("format_leak", "contains prompt or chat-format text",
       r"</?\s*(?:vendor_message|draft_reply|conversation|system|assistant|instructions?|prompt)\b[^>]*>|\[/?(?:inst|sys)\]|<\|[a-z_]+\|>|^\s*(?:system|assistant)\s*:", ),
]

_RETAILERS = [
    "amazon", "daraz", "ebay", "alibaba", "aliexpress", "olx", "flipkart", "walmart", "bestbuy", "best buy",
    "newegg", "noon", "temu", "shein", "pakwheels", "homeshopping", "shophive", "telemart", "czone",
]  # fmt: skip
_URL = re.compile(r"https?://\S+|\bwww\.\S+", re.IGNORECASE)
# Only the clause that belongs to "you said...": it stops at . ! ? , ; or at words like "so" and "but",
# so our own counter later in the sentence is not read as something the vendor quoted.
# A comma or dot between digits (1,200 or 880.50) does not end the clause.
_YOU_PRICE = re.compile(
    r"\byou\s+(?:said|quoted|offered|mentioned|stated|asked\s+for|asked)\b"
    r"((?:(?!\b(?:so|but|and|then|therefore|however|because|since)\b)[^.!?\n,;]|(?<=\d)[.,](?=\d)){0,60})",
    re.IGNORECASE,
)


_CONDITIONAL = re.compile(r"\b(?:if|when|should|may|might|could|would|provided|once|happy\s+to|open\s+to|depending)\b", re.IGNORECASE)
_QUANTITY_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
# A quantity is a small whole number or a number word. Digits that are part of a price ($651, 1,200), a model number,
# a percentage or a size (16GB) are not quantities.
_QUANTITY = re.compile(
    r"(?<![\d$£€.,])\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\b(?![\d.,]*\d)(?!\s*(?:%|gb|tb|mb|inch|hz|years?|days?|months?))",
    re.IGNORECASE,
)
_BUYING_QUANTITY = re.compile(
    r"\b(?:buy|order|purchase|take)\s+(?:up\s+to\s+|about\s+|around\s+)?(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\b"
    r"(?![\d.,]*\d)(?!\s*(?:%|gb|tb|mb|inch|hz|years?|days?|months?))",
    re.IGNORECASE,
)


def _sentence_around(draft: str, start: int, end: int) -> str:
    a = max(draft.rfind(c, 0, start) for c in ".!?\n") + 1
    ends = [i for i in (draft.find(c, end) for c in ".!?\n") if i != -1]
    return draft[a : (min(ends) + 1 if ends else len(draft))]


def _largest_quantity(text: str) -> int:
    nums = [int(w) if w.isdigit() else _QUANTITY_WORDS[w.lower()] for w in _QUANTITY.findall(text)]
    return max(nums, default=1)


def _approved_by_buyer(rule_id: str, sentence: str, matched: str, facts: "ApprovedFacts") -> bool:
    """True when the buyer approved this kind of statement, and it is worded as a condition within what they approved."""
    if not _CONDITIONAL.search(sentence):
        return False  # a firm promise is never allowed. Only "if the price is good..." style.
    if rule_id == "bulk_order":
        return facts.may_buy_quantity >= 2 and _largest_quantity(sentence) <= facts.may_buy_quantity
    if rule_id == "repeat_business":
        return facts.may_buy_again
    if rule_id == "referral_promise":
        return facts.may_refer
    if rule_id == "will_commit":
        verb = re.sub(r"^.*?\b(order|buy|purchase|take)\b.*$", r"\1", matched.lower()) if re.search(r"\b(order|buy|purchase|take)\b", matched.lower()) else ""
        if verb == "buy" and re.search(r"\bagain\b", sentence, re.IGNORECASE):
            return facts.may_buy_again
        if verb in ("order", "buy", "purchase", "take"):
            if facts.may_buy_quantity >= 2 and _largest_quantity(sentence) <= facts.may_buy_quantity:
                return True
            return facts.may_buy_again and bool(re.search(r"\bagain\b", sentence, re.IGNORECASE))
    return False


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _approved_prices(facts: ApprovedFacts) -> tuple[list[float], list[float]]:
    exact = list(facts.vendor_prices)
    if facts.counter_price is not None:
        exact.append(facts.counter_price)
    research = [v for v in (facts.research_low, facts.research_median, facts.research_high) if v is not None]
    return exact, research


def run_rules(draft: str, facts: ApprovedFacts) -> list[Finding]:
    findings: list[Finding] = []

    if not draft.strip():
        return [Finding("empty_draft", "block", "The draft is empty.")]
    if len(draft) > MAX_DRAFT_CHARS:
        findings.append(Finding("too_long", "block", f"The draft is too long ({len(draft)} characters). Keep it short."))

    for rule in RULES:
        if rule.only_negotiating and facts.phase == "closing":
            continue
        m = rule.pattern.search(draft)
        if m:
            if _approved_by_buyer(rule.id, _sentence_around(draft, m.start(), m.end()), m.group(0), facts):
                continue
            findings.append(Finding(rule.id, rule.kind, rule.reason, m.group(0).strip()[:80]))

    # How many units we say we would buy must stay within what the buyer approved, and "more than one" must be a condition.
    for m in _BUYING_QUANTITY.finditer(draft):
        word = m.group(1).lower()
        qty = int(word) if word.isdigit() else _QUANTITY_WORDS[word]
        sentence = _sentence_around(draft, m.start(), m.end())
        if qty > facts.may_buy_quantity:
            findings.append(Finding("buying_quantity", "block", f"Says the buyer would buy {qty}, more than the buyer approved ({facts.may_buy_quantity}).", m.group(0)))
        elif qty >= 2 and not _CONDITIONAL.search(sentence):
            findings.append(Finding("buying_quantity", "block", "Makes a firm promise to buy more than one. It may only be a condition.", m.group(0)))

    # Prices: only the counter, prices the vendor said, and the research figures
    exact, research = _approved_prices(facts)
    known = numbers_in(" ".join([facts.item, *facts.must_haves]))
    for mention in extract_prices(draft, known):
        ok = any(_close(mention.value, p, PRICE_TOLERANCE) for p in exact) or any(
            _close(mention.value, r, RESEARCH_TOLERANCE) for r in research
        )
        if not ok:
            findings.append(Finding("price_not_approved", "block", "States a price that is not approved.", mention.raw))

    # A price attributed to the vendor must be one they really said
    for m in _YOU_PRICE.finditer(draft):
        for mention in extract_prices(m.group(1), known):
            if not any(_close(mention.value, p, PRICE_TOLERANCE) for p in facts.vendor_prices):
                findings.append(Finding("misquoted_vendor_price", "block", "Says the vendor quoted a price they did not.", mention.raw))

    # Retailers and links that are not in the research sources
    source_text = " ".join(f"{s.title} {s.url}" for s in facts.sources).lower()
    low = draft.lower()
    for name in _RETAILERS:
        if re.search(rf"\b{re.escape(name)}\b", low) and name not in source_text:
            findings.append(Finding("unapproved_source", "block", f"Names '{name}', which is not one of the research sources.", name))
    for m in _URL.finditer(draft):
        if not any(s.url and s.url.lower() in m.group(0).lower() for s in facts.sources):
            findings.append(Finding("unapproved_link", "block", "Contains a link that is not a research source.", m.group(0)[:60]))

    return findings


@dataclass
class RuleOutcome:
    blocking: list[Finding] = field(default_factory=list)
    to_verify: list[Finding] = field(default_factory=list)


def split(findings: list[Finding]) -> RuleOutcome:
    out = RuleOutcome()
    for f in findings:
        (out.blocking if f.kind == "block" else out.to_verify).append(f)
    return out
