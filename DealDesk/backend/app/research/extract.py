"""Reads prices off search results. The model READS, code VERIFIES.

The model is shown the search snippets and asked which ones are for sale at a clear price. Then code
checks every answer against the snippet itself, because a model can invent a plausible price:
  - the price must literally appear in the title or snippet
  - a currency sign in the snippet must not contradict the currency the model claims
  - the snippet must really be about the item (enough of its words appear)
  - the currency must be one we can convert
Anything that fails a check is thrown away.
"""

import re
from typing import Literal

from pydantic import BaseModel

from app.core.llm import LLM, UNTRUSTED_NOTICE, llm_label, untrusted
from app.guardrails.prices import extract_prices
from app.research.fx import SUPPORTED
from app.research.search import SearchHit

MIN_ITEM_OVERLAP = 0.6  # share of the item's words that must appear in the listing
MAX_PRICE = 1_000_000_000

_STOP = {"the", "and", "for", "with", "new", "price", "buy", "gb", "tb"}
_SIGN_TO_CURRENCY = {"$": {"USD"}, "£": {"GBP"}, "€": {"EUR"}}
_WORD_TO_CURRENCY = {
    "usd": "USD", "dollar": "USD", "dollars": "USD", "pkr": "PKR", "rs": "PKR", "rupees": "PKR", "rupee": "PKR",
    "aed": "AED", "dirham": "AED", "dirhams": "AED", "sar": "SAR", "riyal": "SAR", "riyals": "SAR",
    "gbp": "GBP", "pounds": "GBP", "pound": "GBP", "eur": "EUR", "euro": "EUR", "euros": "EUR",
}  # fmt: skip

SYSTEM_PROMPT = f"""You read web search results for a buyer who wants to know the market price of an item.
Results are numbered. For each result that is a listing or article stating a clear PRICE for the item the buyer wants,
return one entry. Skip results with no clear price, and results about other products or accessories.
{UNTRUSTED_NOTICE}

For each entry give:
- result: the result number
- price: the number exactly as written for ONE unit of the item (no conversion, no tax added)
- currency: the currency code (USD, PKR, AED, GBP, EUR or SAR)
- condition: new, used, refurbished or unknown
- seller: the store or website name if shown, otherwise empty
- matches_item: true if the listing is for the SAME model and has the required features. A different color, storage size or RAM version of the same model STILL counts as the same model, so set true. Set false only for a different model, an accessory or a different product

Never invent a price. If the price is not in the text, do not return an entry. Answer with an empty list if nothing fits."""


class ExtractedOffer(BaseModel):
    result: int
    price: float
    currency: str
    condition: Literal["new", "used", "refurbished", "unknown"] = "unknown"
    seller: str = ""
    matches_item: bool = False


class Extraction(BaseModel):
    offers: list[ExtractedOffer] = []


class RawOffer(BaseModel):
    price: float
    currency: str
    condition: str
    seller: str
    url: str
    title: str


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP and (len(t) >= 2 or t.isdigit())}


def item_overlap(listing_text: str, item_text: str) -> float:
    """How much of the item's wording appears in the listing (0 to 1)."""
    wanted = _tokens(item_text)
    if not wanted:
        return 0.0
    return len(wanted & _tokens(listing_text)) / len(wanted)


def _currency_conflict(raw: str, claimed: str) -> bool:
    """True when the text beside the price names a different currency than the model claimed."""
    for sign, allowed in _SIGN_TO_CURRENCY.items():
        if sign in raw and claimed not in allowed:
            return True
    for word in re.findall(r"[a-z]+", raw.lower()):
        c = _WORD_TO_CURRENCY.get(word)
        if c and c != claimed:
            return True
    return False


def verify(offer: ExtractedOffer, hits: list[SearchHit], item_text: str) -> RawOffer | None:
    """Returns the offer if it passes every check, otherwise None."""
    if not (1 <= offer.result <= len(hits)) or not offer.matches_item:
        return None
    hit = hits[offer.result - 1]
    currency = offer.currency.strip().upper()
    if currency not in SUPPORTED or not (0 < offer.price < MAX_PRICE):
        return None

    text = f"{hit.title}\n{hit.content}"
    if item_overlap(text, item_text) < MIN_ITEM_OVERLAP:
        return None

    # The price must really be written there WITH a currency marker. A bare number such as 9530 in
    # "XPS 15 9530" is a model number, and a fooled model must not be able to pass it off as a price.
    mentions = [
        m for m in extract_prices(text) if m.marked and abs(m.value - offer.price) <= max(0.01, offer.price * 0.001)
    ]
    if not mentions:
        return None
    if all(_currency_conflict(m.raw, currency) for m in mentions):
        return None

    return RawOffer(
        price=offer.price,
        currency=currency,
        condition=offer.condition,
        seller=offer.seller.strip()[:80],
        url=hit.url,
        title=hit.title[:200],
    )


WINDOW_RADIUS = 110  # characters of text kept on each side of a price
MAX_WINDOWS = 3  # per result


def price_windows(hit: SearchHit) -> str:
    """Only the text around prices that carry a currency marker. A search snippet is mostly irrelevant text,
    so cutting it down makes the model's job smaller, faster and more focused. Empty if there is no such price."""
    text = f"{hit.title}\n{hit.content}"
    spans: list[list[int]] = []
    for m in extract_prices(text):
        if not m.marked or m.pos < 0:
            continue
        a, b = max(0, m.pos - WINDOW_RADIUS), min(len(text), m.pos + WINDOW_RADIUS)
        if spans and a <= spans[-1][1]:
            spans[-1][1] = b  # overlapping windows become one
        else:
            spans.append([a, b])
    parts = [re.sub(r"\s+", " ", text[a:b]).strip() for a, b in spans[:MAX_WINDOWS]]
    return " ... ".join(parts)


def _results_block(hits: list[SearchHit]) -> str:
    """Numbered by their position in the FULL list, so the model's answers map back to the right result."""
    parts = []
    for i, h in enumerate(hits, start=1):
        windows = price_windows(h)
        if windows:  # a result with no marked price cannot give a verified price, so the model never reads it
            parts.append(f"{i}. {h.title[:120]}\n   {windows}")
    return untrusted("search_results", "\n\n".join(parts))


async def extract_offers(
    hits: list[SearchHit], item_text: str, must_haves: list[str], llm: LLM, deal_id: str | None = None
) -> list[RawOffer]:
    """One model call for all the results of one search. Raises LLMError if the model cannot answer."""
    if not hits or not any(price_windows(h) for h in hits):
        return []
    want = f"Item wanted: {item_text}. Required features: {', '.join(must_haves) or 'none'}."
    with llm_label("Researcher", "read prices from the results of one search"):
        out = await llm.complete_json(
            "main", SYSTEM_PROMPT, untrusted("buyer_request", want) + "\n\n" + _results_block(hits), Extraction, deal_id
        )
    verified = (verify(o, hits, item_text) for o in out.offers)
    return [o for o in verified if o is not None]
