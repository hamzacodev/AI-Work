"""The Closer and the user's decisions: accept, counter, reject. Plain code, no AI.

In easy words: the agent never decides to buy. When YOU press Accept, this file finishes the deal:
  - the plain-code check says whether you may accept (above your maximum needs an explicit confirmation),
  - the Closer writes ONE message to the accepted vendor only: the price, cash on delivery, your address and phone,
  - every other vendor is closed and never sees your address or phone,
  - the Limit Checker (closing phase) approves the message before it is saved.
The closing message is a fixed template, so no wording can invent anything. Numbers and address come from code.
"""

from app.agents.fact_rules import Turn
from app.core.money import format_price
from app.guardrails.limit_checker import (
    Context,
    DealLimits,
    check_decision,
    check_outgoing,
    compute_ceiling,
)
from app.guardrails.prices import numbers_in
from app.schemas.records import DealRecord, DealStore, Event, Outbound, VendorRecord


class DecisionError(Exception):
    """The decision cannot go ahead. `status` is the HTTP code, `code` a short name the website can read."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class NeedsConfirmation(Exception):
    """The decision is allowed only if the user confirms it (above the maximum, or a counter above the ceiling)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def closing_message(deal: DealRecord, vendor: VendorRecord, price: float) -> str:
    """The one message that contains the address and phone. A fixed template: nothing to invent."""
    parts = [
        f"Hello {vendor.name}, thank you. We accept your price of {format_price(price, deal.currency)} for the {deal.item}.",
        "Payment will be cash on delivery.",
        f"Please deliver to: {deal.address}.",
    ]
    if deal.phone:
        parts.append(f"Phone: {deal.phone}.")
    parts.append("Please confirm the delivery date.")
    return " ".join(parts)


def _limits(deal: DealRecord) -> DealLimits:
    return DealLimits(max_price=deal.max_price, ceiling_ratio=deal.ceiling_ratio)


async def _load(store: DealStore, deal_id: str, vendor_id: str) -> tuple[DealRecord, VendorRecord]:
    try:
        deal = await store.get(deal_id)
    except KeyError:
        raise DecisionError(404, "deal_not_found", "Deal not found.") from None
    vendor = deal.vendors.get(vendor_id)
    if vendor is None:
        raise DecisionError(404, "vendor_not_found", "Vendor not found.")
    return deal, vendor


def _open(deal: DealRecord, vendor: VendorRecord) -> None:
    if deal.status == "accepted":
        raise DecisionError(409, "already_accepted", "You already accepted a vendor for this deal.")
    if vendor.status == "blocked":
        raise DecisionError(409, "vendor_blocked", "This vendor was blocked by the Safety Guard.")
    if vendor.status == "closed":
        raise DecisionError(409, "vendor_closed", "This conversation is closed.")


async def accept(store: DealStore, deal_id: str, vendor_id: str, confirm_over_limit: bool = False, actor: str = "user") -> None:
    deal, vendor = await _load(store, deal_id, vendor_id)
    _open(deal, vendor)
    if vendor.offer is None:
        raise DecisionError(409, "no_offer", "This vendor has not given a price yet, so there is nothing to accept.")
    verdict = check_decision("accept", vendor.offer, _limits(deal), confirm_over_limit, actor=actor)  # type: ignore[arg-type]
    if not verdict.allowed:
        if verdict.requires_confirmation:
            raise NeedsConfirmation(verdict.reason)
        raise DecisionError(403, "not_allowed", verdict.reason)

    text = closing_message(deal, vendor, vendor.offer)
    gate = check_outgoing(
        text,
        Context(
            max_price=deal.max_price,
            recipient=vendor.contact,
            vendor_contacts=frozenset(v.contact for v in deal.vendors.values()),
            ceiling_ratio=deal.ceiling_ratio,
            vendor_offer=vendor.offer,
            vendor_prices=tuple(vendor.offers_so_far),
            known_numbers=numbers_in(" ".join([deal.item, *deal.must_haves])),
            address=deal.address,
            phone=deal.phone,
            phase="closing",
            accepted_contact=vendor.contact,
            rounds=vendor.rounds,
            max_rounds=max(deal.max_rounds, vendor.rounds),
        ),
    )
    if not gate.allowed:  # fail closed: if the message is not safe, nothing is sent and nothing is accepted
        raise DecisionError(409, "closing_blocked", "The confirmation message did not pass the safety check: " + "; ".join(gate.violations))

    vendor.conversation.append(Turn(sender="agent", text=text))
    vendor.events.append(Event("Closer", f"You accepted {format_price(vendor.offer, deal.currency)}. The Closer sent the confirmation, cash on delivery, with your address, to this vendor only."))
    vendor.status, vendor.stop_reason, vendor.recommendation = "closed", "accepted", None
    for other in deal.vendors.values():
        if other.vendor_id != vendor_id and other.status != "blocked":
            other.status, other.stop_reason = "closed", "other_vendor_accepted"
            other.events.append(Event("Manager", "You accepted another vendor, so this chat is closed. Nothing was sent to this vendor."))
    deal.status, deal.accepted_vendor_id, deal.accepted_price = "accepted", vendor_id, vendor.offer
    await store.save(deal)


async def counter(store: DealStore, deal_id: str, vendor_id: str, price: float | None, confirm_over_limit: bool = False) -> Outbound:
    """The user counters by hand. The price is the user's, the wording is fixed, the Limit Checker approves it."""
    deal, vendor = await _load(store, deal_id, vendor_id)
    _open(deal, vendor)
    if price is None or price <= 0:
        raise DecisionError(422, "bad_price", "A price above zero is required.")
    m = lambda n: format_price(n, deal.currency)
    if abs(price - deal.max_price) < 0.005:  # exactly your maximum would show the vendor your limit
        raise DecisionError(
            409, "counter_at_maximum",
            f"A counter of exactly your maximum ({m(deal.max_price)}) would show the vendor your limit, so it is not sent. "
            "Counter a little below or above it.",
        )  # fmt: skip
    if price > deal.max_price and not confirm_over_limit:  # above your own maximum is your right, but only after you confirm
        raise NeedsConfirmation(
            f"This is above your maximum of {m(deal.max_price)}. If the vendor agrees to {m(price)}, you would pay more than you planned. Send it anyway?"
        )
    verdict = check_decision("counter", price, _limits(deal), confirm_over_limit)
    if not verdict.allowed:
        raise NeedsConfirmation(verdict.reason)
    if vendor.offer is not None and price >= vendor.offer:
        raise DecisionError(409, "counter_not_below_offer", "A counter must be below the vendor's current price.")

    text = f"Could you do {format_price(price, deal.currency)}?"
    # A counter between the ceiling and the maximum is allowed once the user confirmed it, so the check uses the maximum as
    # its ceiling. A counter AT or above the maximum is still blocked: it would give the maximum away.
    ceiling_ratio = max(1.0, price / deal.max_price) if price > compute_ceiling(deal.max_price, deal.ceiling_ratio) else deal.ceiling_ratio
    gate = check_outgoing(
        text,
        Context(
            max_price=deal.max_price, recipient=vendor.contact, vendor_contacts=frozenset(v.contact for v in deal.vendors.values()),
            ceiling_ratio=ceiling_ratio, counter_price=price, previous_counter=None, vendor_offer=vendor.offer,
            vendor_prices=tuple(vendor.offers_so_far), rounds=vendor.rounds + 1, max_rounds=max(deal.max_rounds, vendor.rounds + 1),
        ),
    )  # fmt: skip
    if not gate.allowed:
        raise DecisionError(409, "counter_blocked", "That counter was blocked by the safety check: " + "; ".join(gate.violations))

    vendor.conversation.append(Turn(sender="owner", text=text))
    vendor.events.append(Event("You", f"You countered at {format_price(price, deal.currency)}."))
    vendor.last_counter, vendor.rounds = price, vendor.rounds + 1
    vendor.status, vendor.stop_reason, vendor.recommendation = "negotiating", None, None
    await store.save(deal)
    return Outbound(deal_id, vendor_id, text, "counter", price)


async def reject(store: DealStore, deal_id: str, vendor_id: str) -> None:
    deal, vendor = await _load(store, deal_id, vendor_id)
    _open(deal, vendor)
    vendor.status, vendor.stop_reason, vendor.recommendation = "closed", "rejected_by_user", None
    vendor.events.append(Event("You", "You rejected this vendor. Nothing was sent."))
    if all(v.status in ("closed", "blocked") for v in deal.vendors.values()):
        deal.status = "rejected"
    await store.save(deal)


async def finish(store: DealStore, deal_id: str, action: str) -> None:
    """stop_and_choose: stop texting every vendor that is still negotiating, so you can choose now.
    reject_all: close every vendor and end the deal. Nothing is sent to anyone."""
    try:
        deal = await store.get(deal_id)
    except KeyError:
        raise DecisionError(404, "deal_not_found", "Deal not found.") from None
    if deal.status == "accepted":
        raise DecisionError(409, "already_accepted", "You already accepted a vendor for this deal.")
    for v in deal.vendors.values():
        if v.status in ("closed", "blocked"):
            continue
        if action == "reject_all":
            v.status, v.stop_reason, v.recommendation = "closed", "rejected_by_user", None
            v.events.append(Event("You", "You rejected all vendors. Nothing was sent."))
        elif v.status == "negotiating":
            v.status, v.stop_reason = "paused", "stopped_by_user"
            v.events.append(Event("You", "You stopped the negotiation to choose now. The agent stops texting this vendor. The chat stays open."))
    if action == "reject_all":
        deal.status = "rejected"
    await store.save(deal)
