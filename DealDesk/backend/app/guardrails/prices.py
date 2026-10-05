"""Finds every price-like amount in a piece of text.

Plain Python, no AI. This is the "eyes" of the Limit Checker: if an amount can
hide from this parser, it can hide from the checker. So it reads many styles:
    $800   800 usd   PKR 220,000   Rs.150000   1,50,000   1.5k   2 lakh
    eight hundred dollars   twelve hundred   one thousand two hundred fifty

Numbers that are clearly not prices (16GB, 3 years, 2026-10-02, 13700H) are
skipped. When it is unsure, it counts the number as a price. A false alarm only
sends a message for a rewrite. A missed price could leak your limit.
"""

import re
from dataclasses import dataclass

CURRENCY = (
    r"usd|us\s?dollars?|dollars?|bucks?|pkr|rs|rupees?|inr|aed|dirhams?|sar|riyals?|gbp|pounds?|eur|euros?"
)

# Western grouping 1,234,567 | Indian grouping 1,50,000 | plain 800 or 800.50
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?|\d+(?:\.\d+)?"
_TOKEN = re.compile(rf"(?<![\w,])(?<!\d\.)({_NUM})")

_SCALE = re.compile(r"\s?(k|thousand|lakhs?|lacs?|crores?|million)\b", re.IGNORECASE)
_SCALE_VALUE = {
    "k": 1e3,
    "thousand": 1e3,
    "lakh": 1e5,
    "lakhs": 1e5,
    "lac": 1e5,
    "lacs": 1e5,
    "crore": 1e7,
    "crores": 1e7,
    "million": 1e6,
}
_PRE_CURRENCY = re.compile(rf"(?:[$£€]|(?<![a-z])(?:{CURRENCY})\.?)\s*$", re.IGNORECASE)
_POST_CURRENCY = re.compile(rf"\s*(?:(?:{CURRENCY})\b|[$£€])", re.IGNORECASE)
_UNIT = re.compile(
    r"\s*(?:gb|tb|mb|inch(?:es)?|hz|mah|mp|years?|yrs?|days?|months?|weeks?|hours?|hrs?|units?|pcs|pieces?"
    r"|nits|fps|cores?|rpm|mm|cm|kg|km|am|pm|percent|x)\b|\s*%|\s*\"",
    re.IGNORECASE,
)
_ATTACHED_WORD = re.compile(r"[A-Za-z]+")

# bare numbers at or above this look like prices ("I can do 790")
BARE_PRICE_MIN = 100

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip
_BIG = {"thousand": 1e3, "lakh": 1e5, "lac": 1e5, "million": 1e6, "crore": 1e7}
_WORD_TOKEN = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class PriceMention:
    value: float
    raw: str
    marked: bool = False  # True when a currency sign or word came with the number (so it is surely money)
    pos: int = -1  # where in the text the number starts


def numbers_in(text: str) -> frozenset[float]:
    """All plain numbers in a text. Used to learn which numbers are model names, like 'XPS 15'."""
    return frozenset(float(m.group(1).replace(",", "")) for m in _TOKEN.finditer(text))


def _digit_prices(text: str, ignore: frozenset[float]) -> list[PriceMention]:
    found: list[PriceMention] = []
    for m in _TOKEN.finditer(text):
        start, end = m.span(1)
        before, after = text[:start], text[end:]
        value = float(m.group(1).replace(",", ""))

        # Dates (2026-10-02), ranges and phone pieces: a digit joined to another number by - or /
        if re.match(r"[-/]\d", after) or re.search(r"\d[-/]$", before):
            continue

        scale_match = _SCALE.match(after)
        rest = after[scale_match.end() :] if scale_match else after

        attached = _ATTACHED_WORD.match(after)
        if attached and not scale_match and not re.fullmatch(CURRENCY, attached.group(0), re.IGNORECASE):
            continue  # 16GB, 13700H, 4B: letters stuck to the number

        has_currency = bool(_PRE_CURRENCY.search(before) or _POST_CURRENCY.match(rest))
        has_unit = bool(_UNIT.match(rest))
        scaled = value * (_SCALE_VALUE[scale_match.group(1).lower()] if scale_match else 1)

        if has_currency:
            is_price = True
        elif has_unit:
            is_price = False
        elif scale_match:
            is_price = True  # 1.5k, 2 lakh
        else:
            is_price = scaled >= BARE_PRICE_MIN and value not in ignore

        if is_price:
            raw = text[max(0, start - 4) : end + (scale_match.end() if scale_match else 0) + 8].strip()
            found.append(PriceMention(scaled, raw, has_currency, start))
    return found


def _words_to_number(words: list[str]) -> float:
    total = 0.0
    current = 0.0
    for w in words:
        if w == "and":
            continue
        if w in _ONES:
            current += _ONES[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = max(current, 1) * 100
        elif w in _BIG:
            total += max(current, 1) * _BIG[w]
            current = 0
    return total + current


def _word_prices(text: str) -> list[PriceMention]:
    low = text.lower()
    tokens = [(m.group(0), m.start(), m.end()) for m in _WORD_TOKEN.finditer(low)]
    numberish = set(_ONES) | set(_TENS) | set(_BIG) | {"hundred", "and"}

    found: list[PriceMention] = []
    i = 0
    while i < len(tokens):
        if tokens[i][0] not in numberish or tokens[i][0] == "and":
            i += 1
            continue
        j = i
        # extend over number words that are separated only by spaces or hyphens
        while (
            j + 1 < len(tokens)
            and tokens[j + 1][0] in numberish
            and re.fullmatch(r"[\s-]+", low[tokens[j][2] : tokens[j + 1][1]])
        ):
            j += 1
        words = [t[0] for t in tokens[i : j + 1]]
        # "2 lakh": the digit reader already counted it, so a lone scale word after a digit is skipped
        if words[0] in _BIG and re.search(r"\d\s*$", low[: tokens[i][1]]):
            i += 1  # skip only that word, the rest ("and fifty thousand") is still read
            continue
        while words and words[-1] == "and":
            words.pop()
            j -= 1
        if words:
            value = _words_to_number(words)
            after = low[tokens[j][2] :]
            has_currency = bool(_POST_CURRENCY.match(after))
            has_unit = bool(_UNIT.match(after))
            if has_currency or (value >= BARE_PRICE_MIN and not has_unit):
                found.append(PriceMention(value, low[tokens[i][1] : tokens[j][2]], has_currency, tokens[i][1]))
        i = j + 1
    return found


def extract_prices(text: str, ignore_numbers: frozenset[float] = frozenset()) -> list[PriceMention]:
    """Every price-like amount in `text`. `ignore_numbers` are plain numbers that belong to the
    item name (like the 15 in 'XPS 15'), which are not prices when written without a currency."""
    return _digit_prices(text, ignore_numbers) + _word_prices(text)
