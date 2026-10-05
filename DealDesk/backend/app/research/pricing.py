"""Turns a pile of found prices into low, median, high and a confidence level.

Pure code. No AI. This is where "numbers come from code" is enforced for research:
the model only READ the prices off web pages, and this file decides what they mean.
"""

import statistics
from dataclasses import dataclass
from urllib.parse import urlparse

from app.schemas.research import Confidence

OUTLIER_BAND = 0.5  # keep prices within median +/- 50%
MIN_FOR_OUTLIERS = 3  # with fewer prices a median is meaningless, so nothing is removed
MIN_FOR_IQR = 5
SPREAD_FOR_HIGH = 0.25  # high confidence needs (high - low) / median at most this
BIG_SPREAD = 0.60  # a spread above this means the prices do not agree: low confidence


@dataclass(frozen=True)
class Offer:
    price: float  # already in the target currency
    url: str
    title: str
    region: str
    seller: str = ""
    condition: str = "unknown"


def domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def clean_offers(offers: list[Offer], want_condition: str = "new") -> list[Offer]:
    """Drops what cannot be trusted: no link, no price, wrong condition, duplicate links."""
    seen: set[str] = set()
    out: list[Offer] = []
    for o in offers:
        if not o.url.startswith(("http://", "https://")) or not domain(o.url):
            continue
        if not (o.price > 0):
            continue
        if want_condition == "new" and o.condition in ("used", "refurbished"):
            continue
        if want_condition != "new" and o.condition == "new":
            continue  # asked for used or refurbished: a brand new price would pull the range up
        key = o.url.lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(o)
    return out


def remove_outliers(offers: list[Offer]) -> tuple[list[Offer], list[Offer]]:
    """Returns (kept, dropped). A $95 charger among $700 laptops, or a $4,000 bundle, is not a market price."""
    if len(offers) < MIN_FOR_OUTLIERS:
        return list(offers), []
    med = statistics.median(o.price for o in offers)
    kept = [o for o in offers if med * (1 - OUTLIER_BAND) <= o.price <= med * (1 + OUTLIER_BAND)]

    if len(kept) >= MIN_FOR_IQR:  # a second, tighter test when there is enough data
        prices = sorted(o.price for o in kept)
        q1, _, q3 = statistics.quantiles(prices, n=4)
        fence = 1.5 * (q3 - q1)
        kept = [o for o in kept if q1 - fence <= o.price <= q3 + fence]

    # If this would throw away more than half of the offers, the prices form two groups (for example 700 and 2500,
    # with the median in the gap) and there is no real "outlier". Keep everything and let the spread say the
    # prices disagree. Throwing everything away would turn "the prices disagree" into "no prices".
    if len(kept) * 2 < len(offers):
        return list(offers), []

    dropped = [o for o in offers if o not in kept]
    return kept, dropped


GROUP_BAND = 1.35  # prices within this factor of the group's lowest price count as the same version of the item
MIN_GROUP = 3


def densest_group(offers: list[Offer]) -> tuple[list[Offer], list[Offer]]:
    """When the prices split into groups (several generations of one laptop, a bundle and a bare unit), keep the biggest group of similar
    prices. On a tie the lower group wins. Returns (kept, dropped); nothing changes when there is no clear group of at least 3."""
    if len(offers) < MIN_GROUP + 1:
        return list(offers), []
    ordered = sorted(offers, key=lambda o: o.price)
    best: list[Offer] = []
    for i, first in enumerate(ordered):
        group = [o for o in ordered[i:] if o.price <= first.price * GROUP_BAND]
        if len(group) > len(best):  # strictly more: the first (lowest) group wins a tie
            best = group
    if len(best) < MIN_GROUP or len(best) == len(offers):
        return list(offers), []
    return best, [o for o in offers if o not in best]


def spread(low: float, median: float, high: float) -> float:
    return (high - low) / median if median > 0 else float("inf")


def confidence_level(n_sources: int, n_regions: int, spread_value: float) -> Confidence:
    """CLAUDE.md section 11, step 7."""
    if n_sources < 2 or spread_value > BIG_SPREAD:
        return "low"
    if n_sources >= 3 and n_regions >= 2 and spread_value <= SPREAD_FOR_HIGH:
        return "high"
    return "medium"


@dataclass(frozen=True)
class Stats:
    low: float
    median: float
    high: float
    n_sources: int
    regions: list[str]
    confidence: Confidence
    spread: float


def compute(offers: list[Offer]) -> Stats | None:
    if not offers:
        return None
    prices = [o.price for o in offers]
    low, med, high = min(prices), statistics.median(prices), max(prices)
    sources = {domain(o.url) for o in offers}
    regions = sorted({o.region for o in offers})
    sp = spread(low, med, high)
    return Stats(
        low=round(low, 2),
        median=round(med, 2),
        high=round(high, 2),
        n_sources=len(sources),
        regions=regions,
        confidence=confidence_level(len(sources), len(regions), sp),
        spread=round(sp, 3),
    )
