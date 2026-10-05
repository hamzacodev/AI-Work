"""Add-ons (free extras) and the EFFECTIVE price. Plain code, no AI.

In easy words: a vendor may say "$720 and a free charger and hands-free". A $720 phone with $35 of extras you actually want
is worth more than a bare $700 phone. This file
  - finds the extras in a vendor message (a closed list, found by patterns, so nothing is made up),
  - works out their value to YOU (from the values you gave, which are YOUR estimates, not market facts),
  - gives the effective price: price minus the value of the extras you want.

A conditional extra ("if you buy at $700 or more we give a free charger") only counts while the price meets the condition.
The effective price is used to compare vendors and to judge "good deal". What you PAY is always the price, so every limit
(your maximum, the ceiling, the Limit Checker) still looks at the price.
"""

import re
from dataclasses import dataclass

from app.guardrails.prices import extract_prices


@dataclass(frozen=True)
class Addon:
    key: str
    label: str  # how it is written in messages to the vendor
    pattern: re.Pattern[str]
    suggested_usd: float  # a starting value shown on the Buy form. The buyer edits it.


def _a(key: str, label: str, pattern: str, suggested: float) -> Addon:
    return Addon(key, label, re.compile(pattern, re.IGNORECASE), suggested)


CATALOG: tuple[Addon, ...] = (
    _a("charger", "charger", r"\b(?:charger|adapter|adaptor|charging\s+(?:brick|cable))\b", 20),
    _a("handsfree", "hands-free", r"\b(?:hands?[\s-]?free|ear\s?phones?|ear\s?buds?|head\s?phones?|airpods?)\b", 15),
    _a("case", "case", r"\b(?:case|cover|pouch)\b", 10),
    _a("screen_protector", "screen protector", r"\b(?:screen\s+(?:protector|guard)|tempered\s+glass|glass\s+protector)\b", 8),
    _a("delivery", "free delivery", r"\b(?:(?:home\s+)?delivery|shipping|courier)\b", 15),
    _a("warranty", "extended warranty", r"\b(?:warranty|guarantee)\b", 30),
    _a("bag", "bag", r"\b(?:bag|backpack|sleeve)\b", 20),
    _a("mouse", "mouse", r"\bmouse\b", 10),
)
BY_KEY = {a.key: a for a in CATALOG}
LABELS = {a.key: a.label for a in CATALOG}
SUGGESTED_USD = {a.key: a.suggested_usd for a in CATALOG}

# The vendor is GIVING it: "free", "included", "we give", "comes with" ...
_GIVES = re.compile(
    r"\b(?:free|complimentary|included|includes|including|bonus|gift|freebie|at\s+no\s+(?:extra\s+|additional\s+)?(?:cost|charge)"
    r"|thrown\s+in|along\s+with|comes?\s+with|come\s+with|we\s+(?:will\s+|'ll\s+)?give|you\s+(?:will\s+|'ll\s+)?get)\b",
    re.IGNORECASE,
)
# ... and not "no free charger", "without charger", "charger costs extra", "sold separately".
_DENIES = re.compile(
    r"\b(?:no|not|never|without|isn'?t|aren'?t|won'?t|excluding|excluded)\b[^.!?\n]{0,25}$"
    r"|\b(?:extra\s+(?:cost|charge)|costs?\s+extra|sold\s+separately|separately|paid|charged\s+extra|at\s+extra)\b",
    re.IGNORECASE,
)
# "if you buy at $700", "on orders over $700": the extra needs this much spent.
_CONDITION = re.compile(
    r"\b(?:if|when|once|above|over|at\s+least|minimum|spend|purchase\s+of|orders?\s+(?:of|over|above)|buy(?:ing)?\s+(?:at|for|above|over))\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?\n]+")
_CLAUSE = re.compile(r"[,;]|\bbut\b|\bhowever\b", re.IGNORECASE)


@dataclass(frozen=True)
class AddonOffer:
    key: str
    min_price: float | None = None  # the extra applies only if the price you pay is at least this much


def find_addons(message: str) -> list[AddonOffer]:
    """The extras the vendor says it GIVES. One entry per extra. Sentences are read one by one."""
    found: dict[str, AddonOffer] = {}
    for m in _SENTENCE.finditer(message):
        sentence = m.group(0)
        if not _GIVES.search(sentence):
            continue
        cond = _CONDITION.search(sentence)
        # only a price that comes AFTER the condition word is a condition: "if you buy at $700", not "Black is $720, free charger if you decide today"
        prices = [p.value for p in extract_prices(sentence) if cond and p.pos >= cond.start()]
        min_price = min(prices) if prices else None
        for clause in _CLAUSE.split(sentence):  # "Free case, but charger sold separately": each part on its own
            for addon in CATALOG:
                hit = addon.pattern.search(clause)
                if hit is None or _DENIES.search(clause[: hit.start()]) or _DENIES.search(clause[hit.end() :]):
                    continue
                old = found.get(addon.key)
                if old is None or (min_price is None and old.min_price is not None):
                    found[addon.key] = AddonOffer(addon.key, min_price)
    return list(found.values())


def strip_addon_words(text: str) -> str:
    """The text without the names of the extras, so "$720 with a free charger" is not read as the price of a charger."""
    for addon in CATALOG:
        text = addon.pattern.sub(" ", text)
    return text


def credit(offered: list[AddonOffer], values: dict[str, float], price: float | None) -> tuple[float, list[str]]:
    """The value to YOU of the extras this vendor gives at this price, and which extras count.
    Only extras you gave a value for count. A conditional extra counts only if the price meets its condition."""
    if price is None:
        return 0.0, []
    total, counted = 0.0, []
    for o in offered:
        value = values.get(o.key, 0.0)
        if value <= 0 or (o.min_price is not None and price < o.min_price - 0.01):
            continue
        total += value
        counted.append(o.key)
    return round(total, 2), counted


def effective_price(price: float, offered: list[AddonOffer], values: dict[str, float]) -> float:
    return round(price - credit(offered, values, price)[0], 2)


def lost_if_price_drops(offered: list[AddonOffer], values: dict[str, float], counter: float) -> list[str]:
    """Extras you value that the vendor gives only from a higher price than `counter`. We ask to keep them."""
    return [o.key for o in offered if values.get(o.key, 0) > 0 and o.min_price is not None and counter < o.min_price - 0.01]


def words(keys: list[str]) -> str:
    """"charger", "charger and hands-free", "charger, hands-free and case" """
    labels = [LABELS[k] for k in keys if k in LABELS]
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1] if labels else ""
