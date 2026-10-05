"""Decides which sentences of a draft need the model's attention.

A question or a polite closing asserts nothing, so it cannot be a false claim. Our own standard
lines and approved research statements are known to be fine. Only the OTHER sentences are sent
to the model. This keeps a small model from inventing problems in honest drafts, and it means
a model call is skipped entirely when the draft has nothing to check.

Be careful when adding to the safe lists: a safe sentence skips the model. Each entry is a
CLOSED template, not a loose keyword.
"""

import re

from app.agents.fact_rules import ApprovedFacts
from app.guardrails.prices import extract_prices

_PRICE = re.compile(
    r"(?:[$£€]|\b(?:usd|pkr|aed|gbp|eur|sar|rs\.?)\s*)?\s*\d[\d,]*(?:\.\d+)?\s*(?:k\b|usd|pkr|aed|gbp|eur|sar|dollars?|rupees?)?",
    re.IGNORECASE,
)

_PLEASANT = [
    r"(?:thank you|thanks)(?: very much| so much| again)?(?: for (?:your|the)(?: quick| prompt| kind| helpful)? (?:reply|response|message|offer|information|details|update|time|help))?",
    r"(?:hello|hi|dear [a-z ]{1,30}|good (?:morning|afternoon|evening))",
    r"(?:best|kind|warm)? ?regards",
    r"looking forward to (?:your (?:reply|response)|hearing from you)",
    r"have a (?:good|great|nice) day",
]
_POLICY = [
    r"we will share delivery details once we confirm the order",
    r"only cash on delivery is possible(?: for us)?",
    r"payment will be cash on delivery",
    r"we will pay cash on delivery",
    r"we (?:can|would like to) pay cash on delivery",
    r"we will get back to you(?: shortly| soon)?",
    r"please let us know(?: if you can improve the price| if that works)?",
]
# research statements, with prices written as P and sources as SRC
_RESEARCH = [
    r"similar listings are (?:around|about|near) P(?: SRC)?",
    r"similar listings (?:range|are) (?:from|between) P (?:to|and) P(?: (?:on|at|from) SRC(?: and SRC)?)?",
    r"(?:prices|listings)(?: we have seen| we saw| we found| seen| found)?(?: range| ranged)? ?(?:from|between) P (?:to|and) P(?: (?:on|at|from) SRC(?: and SRC)?)?",
    r"our research shows (?:prices|listings)?(?: between| from) P (?:and|to) P",
    r"(?:listings|prices) (?:on|at) SRC (?:are|is) (?:around|about) P",
]
# statements of our own counter price. Every price in them must be the counter price.
_COUNTER = [
    r"(?:our|my) (?:counter )?(?:offer|proposal|counter) is P",
    r"we (?:can |could |would like to )?(?:offer|propose|suggest|counter(?: with)?) P",
]
_STOP = {
    "you", "mentioned", "said", "quoted", "stated", "offered", "the", "a", "an", "is", "are", "of", "and", "in",
    "at", "for", "to", "that", "it", "with", "your", "price", "prices", "also", "so", "as",
}  # fmt: skip


def split_sentences(draft: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", draft.strip())
    return [p.strip() for p in parts if p.strip()]


def _normalise(sentence: str, facts: ApprovedFacts) -> str:
    s = sentence
    for src in sorted((x.title for x in facts.sources if x.title), key=len, reverse=True):
        s = re.sub(re.escape(src), " SRC ", s, flags=re.IGNORECASE)
    s = _PRICE.sub(" P ", s)
    s = re.sub(r"[^A-Za-z ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # keep P and SRC upper case, everything else lower case
    return " ".join(w if w in ("P", "SRC") else w.lower() for w in s.split())


def _fullmatch_any(templates: list[str], text: str) -> bool:
    return any(re.fullmatch(t, text) for t in templates)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP}


def is_safe(sentence: str, facts: ApprovedFacts) -> bool:
    """True if this sentence cannot be a false claim, so the model does not need to read it."""
    s = sentence.strip()
    if s.endswith("?"):
        return True  # a question asserts nothing

    norm = _normalise(s, facts)
    if _fullmatch_any(_PLEASANT, norm.lower()) or _fullmatch_any(_POLICY, norm.lower()):
        return True
    if _fullmatch_any(_RESEARCH, norm):
        return True
    if _fullmatch_any([t.replace("P", "P") for t in _COUNTER], norm.lower().replace(" p", " P")):
        prices = extract_prices(s)
        return facts.counter_price is not None and bool(prices) and all(abs(p.value - facts.counter_price) <= 0.01 for p in prices)

    # "You mentioned $880 and delivery in 3 days." is safe if every word really came from the vendor
    if re.match(r"you (?:mentioned|said|quoted|stated|offered)\b", s, re.IGNORECASE):
        vendor_text = " ".join(t.text for t in facts.conversation if t.sender == "vendor")
        mine = _words(s)
        theirs = _words(vendor_text)
        return bool(mine) and len(mine & theirs) / len(mine) >= 0.8
    return False


def residual_statements(draft: str, facts: ApprovedFacts) -> list[str]:
    """The sentences that still need the model to read them."""
    return [s for s in split_sentences(draft) if not is_safe(s, facts)]
