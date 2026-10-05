"""The Best Offer Tracker: the view ABOVE all the vendors of one deal. Plain code, no AI.

In easy words: the strategy (strategy.py) talks to one vendor at a time. This file looks at all of them.
  - Which vendor has the lowest real price right now?
  - Which number may we tell the OTHER vendors ("I already have an offer of $640"), without saying who?
  - Is anyone still negotiating, or is everybody done and the user can choose?

Rules this file follows:
  - A chat is never closed. A vendor is "paused" (we stop texting) and wakes up if they write again.
  - A price used as leverage must be a real, verified vendor price, lower than the price of the vendor we tell,
    and at or below the market price (we never advertise a number higher than our own goal).
  - The tracker never buys anything. It only recommends. The user decides (CLAUDE.md rule 7).
"""

from dataclasses import dataclass, field
from typing import Literal

from app.core.money import format_price

SAME_PRICE = 0.01
MIN_CREDIBLE_RATIO = 0.5  # an offer under half the market price is shown with a warning, not used as leverage

VendorStatus = Literal["negotiating", "paused", "blocked"]


@dataclass(frozen=True)
class VendorState:
    """What the tracker needs to know about one vendor. The agent loop fills it from the database."""

    vendor_id: str
    name: str
    offer: float | None = None  # the vendor's latest VERIFIED price (Safety Guard ok, Offer Reader read it)
    status: VendorStatus = "negotiating"
    stop_reason: str | None = None  # why we paused: "firm_price", "round_limit", "stalled", "good_price", "met_counter", "at_limit"
    firm: bool = False  # the vendor said the price is final
    rounds: int = 0  # messages we already sent to this vendor
    last_leverage: float | None = None  # the competing price we already told this vendor
    credit: float = 0.0  # what the free extras this vendor gives are worth to the buyer (the buyer's estimate)
    addons: tuple[str, ...] = ()  # the extras that count (labels), for the summary


@dataclass(frozen=True)
class RankedOffer:
    vendor_id: str
    name: str
    price: float
    firm: bool
    status: VendorStatus
    stop_reason: str | None
    warning: str | None = None
    credit: float = 0.0
    effective: float = 0.0  # price minus the extras you value. This is what vendors are compared on.
    addons: tuple[str, ...] = ()


@dataclass(frozen=True)
class DealSummary:
    best: RankedOffer | None
    ranking: list[RankedOffer]  # lowest price first
    still_negotiating: int
    all_done: bool
    saved: float | None  # market median minus the best price (can be negative)
    saved_pct: float | None
    headline: str
    warnings: list[str] = field(default_factory=list)


def is_credible(price: float, median: float | None) -> bool:
    """A price far below the market is probably a mistake or a trap. It is shown, but not trusted as leverage."""
    return median is None or price >= MIN_CREDIBLE_RATIO * median


def _usable(v: VendorState) -> bool:
    return v.status != "blocked" and v.offer is not None and v.offer > 0


def best_offer(states: list[VendorState], median: float | None = None) -> VendorState | None:
    """The vendor with the lowest credible price. A tie goes to the vendor listed first."""
    pool = [v for v in states if _usable(v) and is_credible(v.offer, median)]  # type: ignore[arg-type]
    return min(pool, key=lambda v: v.offer) if pool else None  # type: ignore[arg-type,return-value]


def leverage_for(
    vendor_id: str, states: list[VendorState], median: float | None, ceiling: float | None = None
) -> float | None:
    """The number we may tell this vendor ("I already have an offer of ..."), or None.

    It is the best price among the OTHER vendors, and only when it is
      - lower than this vendor's own price (telling a cheaper vendor about a higher price would raise their price),
      - (no upper limit: a price another vendor really gave is a fact, not an offer from us, so it may be above the market or our ceiling),
      - credible (not far below the market).
    """
    me = next((v for v in states if v.vendor_id == vendor_id), None)
    if me is None or not _usable(me):
        return None
    others = [v for v in states if v.vendor_id != vendor_id]
    best = best_offer(others, median)
    if best is None or best.offer is None or best.offer >= me.offer - SAME_PRICE:  # type: ignore[operator]
        return None
    return best.offer


def others_active(vendor_id: str, states: list[VendorState]) -> bool:
    """Is any OTHER vendor still being negotiated with? If so, one vendor's good price does not end the deal."""
    return any(v.vendor_id != vendor_id and v.status == "negotiating" for v in states)


REENGAGE_REASONS = ("good_price", "near_market_low", "met_counter", "confirmed", "at_limit", "stalled", "refused", "firm_price")  # NOT "firm_price" (they said final) or "round_limit"


def reengage_candidates(states: list[VendorState], median: float | None, ceiling: float | None, max_rounds: int) -> list[str]:
    """Paused vendors we should write to again, because ANOTHER vendor has since given a better price we have
    not told them about yet. The chat was never closed, so we just continue it. Rounds still apply."""
    out = []
    for v in states:
        if v.status != "paused" or v.stop_reason not in REENGAGE_REASONS or v.rounds >= max_rounds:
            continue
        lever = leverage_for(v.vendor_id, states, median, ceiling)
        if lever is not None and lever != v.last_leverage:
            out.append(v.vendor_id)
    return out


def summarize(states: list[VendorState], median: float | None, currency: str = "USD") -> DealSummary:
    """The ranking compares EFFECTIVE prices (price minus the free extras you value). What you pay is still the price."""
    m = lambda n: format_price(n, currency)
    usable = [v for v in states if _usable(v)]
    ranking = [
        RankedOffer(
            v.vendor_id,
            v.name,
            v.offer,  # type: ignore[arg-type]
            v.firm,
            v.status,
            v.stop_reason,
            None if is_credible(v.offer, median) else "Far below the market price. Check that this offer is real.",  # type: ignore[arg-type]
            v.credit,
            round(v.offer - v.credit, 2),  # type: ignore[operator]
            v.addons,
        )
        for v in sorted(usable, key=lambda v: v.offer - v.credit)  # type: ignore[operator]
    ]
    credible = [r for r in ranking if is_credible(r.price, median)]
    best = credible[0] if credible else None  # ties go to the vendor listed first (sorted() is stable)
    active = sum(1 for v in states if v.status == "negotiating")
    warnings = [f"{r.name}: {r.warning}" for r in ranking if r.warning]

    saved = saved_pct = None
    if best is None:
        headline = "No vendor has given a usable price yet."
    else:
        if median:
            saved = round(median - best.effective, 2)
            saved_pct = round(saved / median * 100, 1)
        counted = f" ({m(best.effective)} counting the extras you value, your estimate)" if best.credit > 0 else ""
        if saved is not None and saved > 0:
            headline = f"Best deal so far: {best.name} at {m(best.price)}{counted}. The market price is {m(median)}, so you save {m(saved)} ({saved_pct:g}%)."  # type: ignore[arg-type]
        elif saved is not None:
            headline = f"Best offer so far: {best.name} at {m(best.price)}{counted}. That is not below the market price of {m(median)}."  # type: ignore[arg-type]
        else:
            headline = f"Best offer so far: {best.name} at {m(best.price)}{counted}."
    if best is not None:
        headline += " You decide. The agent never accepts for you." if active == 0 else f" Still negotiating with {active} vendor{'s' if active != 1 else ''}."
    return DealSummary(best, ranking, active, active == 0, saved, saved_pct, headline, warnings)
