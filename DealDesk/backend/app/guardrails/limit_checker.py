"""The Limit Checker: the last gate before any message leaves DealDesk.

Plain Python. No AI, no network. It only imports the standard library and our
own price parser, and a test enforces that. That is the whole point: no prompt,
however clever, can talk its way past code that never reads prompts.

Two entry points:
    check_outgoing(message, ctx)  -> may this message be sent to this vendor?
    check_decision(action, ...)   -> may this user decision go ahead?
"""

import math
import re
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from app.guardrails.prices import extract_prices

MONEY_TOLERANCE = 0.01  # prices are equal if they differ by one cent or less
RESEARCH_TOLERANCE = 1.0  # a research figure may be shown rounded to a whole unit
NEAR_MAX_FRACTION = 0.005  # research figures within 0.5% of the maximum are never allowed

# Things a vendor may ask for that DealDesk never agrees to. Only cash on delivery is allowed.
_PAYMENT_TERMS = re.compile(
    r"\b(?:advance|prepay\w*|upfront|up-front|bank\s+transfer|wire(?:\s+transfer)?|deposit|down\s+payment"
    r"|gift\s*cards?|crypto\w*|bitcoin|btc|usdt|ethereum|western\s+union|moneygram|zelle|venmo|jazz\s?cash"
    r"|easy\s?paisa|iban)\b",
    re.IGNORECASE,
)
_NEGATION_BEFORE = re.compile(
    r"\b(?:no|not|never|cannot|can't|cant|won't|wont|don't|dont|without|unable|decline|refuse)\b[^.!?\n]{0,30}$",
    re.IGNORECASE,
)
# "Advance payment is not possible": the refusal comes right after the term (and maybe the word "payment")
_NEGATION_AFTER = re.compile(
    r"^(?:\s+(?:payment|transfer|money|deposit))?\W*(?:is|are|will\s+be|would\s+be)\s+(?:not|never)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Context:
    """Everything the checker needs to know. The caller (the agent graph) fills it in from the database."""

    max_price: float
    recipient: str
    vendor_contacts: frozenset[str]
    ceiling_ratio: float = 0.95
    counter_price: float | None = None  # the price the code decided to offer
    previous_counter: float | None = None
    vendor_offer: float | None = None  # the vendor's latest offer
    vendor_prices: tuple[float, ...] = ()  # every price the vendor has already said
    competing_offer: float | None = None  # the best price ANOTHER vendor gave, which we may state (never a name)
    research_figures: tuple[float, ...] = ()  # low, median, high
    walk_away_prices: tuple[float, ...] = ()
    known_numbers: frozenset[float] = field(default_factory=frozenset)  # numbers in the item name
    address: str = ""
    phone: str | None = None
    phase: Literal["negotiating", "closing"] = "negotiating"
    accepted_contact: str | None = None
    rounds: int = 0
    max_rounds: int = 3
    sending_for_real: bool = False
    real_send_enabled: bool = False
    owner_allowlist: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Result:
    allowed: bool
    violations: list[str]


def compute_ceiling(max_price: float, ratio: float = 0.95) -> float:
    """The highest counter DealDesk may ever offer. Always below the maximum, so the maximum cannot leak."""
    exact = Decimal(str(max_price)) * Decimal(str(ratio))
    return float(exact.quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _close(a: float, b: float, tol: float = MONEY_TOLERANCE) -> bool:
    return math.isclose(a, b, abs_tol=tol, rel_tol=0)


def _norm_contact(c: str) -> str:
    return c.strip().lower()


def _norm_text(t: str) -> str:
    return " " + re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t.lower())).strip() + " "


def _leaks_phone(message: str, phone: str | None) -> bool:
    if not phone:
        return False
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7:
        return False
    tail = digits[-9:]  # the last digits survive differences like +92 300... vs 0300...
    return tail in re.sub(r"\D", "", message)


def _address_parts(address: str) -> list[str]:
    parts = [_norm_text(p) for p in re.split(r"[,\n;]", address)]
    return [p for p in parts if len(p.strip()) >= 5]


def _leaks_address(message: str, address: str) -> bool:
    if not address.strip():
        return False
    msg = _norm_text(message)
    return any(p in msg for p in _address_parts(address))


def _strip_private(message: str, address: str, phone: str | None) -> str:
    """In the closing message the address and phone are allowed, so remove them before reading prices."""
    out = message
    for part in re.split(r"[,\n;]", address):
        part = part.strip()
        if len(part) >= 3:
            out = re.sub(re.escape(part), " ", out, flags=re.IGNORECASE)
    if phone:
        out = re.sub(re.escape(phone.strip()), " ", out)
        out = re.sub(r"\+?\d[\d\s\-()]{6,}\d", " ", out)  # the phone written in another style
    return out


def find_payment_commitments(message: str) -> list[str]:
    """Payment words are blocked unless the sentence refuses them ("we cannot pay in advance")."""
    bad = []
    for m in _PAYMENT_TERMS.finditer(message):
        before = message[: m.start()]
        before = re.split(r"[.!?\n]", before)[-1]  # same sentence only
        if _NEGATION_BEFORE.search(before) or _NEGATION_AFTER.match(message[m.end() :]):
            continue
        bad.append(m.group(0))
    return bad


def check_outgoing(message: str, ctx: Context) -> Result:
    v: list[str] = []
    ceiling = compute_ceiling(ctx.max_price, ctx.ceiling_ratio)

    # Rule 8: only vendors in this deal's list
    contacts = {_norm_contact(c) for c in ctx.vendor_contacts}
    if _norm_contact(ctx.recipient) not in contacts:
        v.append(f"recipient_not_in_vendor_list: {ctx.recipient}")

    # Rule 10: real sending only to the owner's own test addresses
    if ctx.sending_for_real:
        if not ctx.real_send_enabled:
            v.append("real_send_disabled: REAL_SEND_ENABLED is false")
        elif _norm_contact(ctx.recipient) not in {_norm_contact(a) for a in ctx.owner_allowlist}:
            v.append(f"real_send_not_allowlisted: {ctx.recipient}")

    # Rule 9: round cap
    if ctx.rounds > ctx.max_rounds:
        v.append(f"round_cap_exceeded: {ctx.rounds} > {ctx.max_rounds}")

    # Rule 6: address and phone only in the closing message, to the accepted vendor
    closing_ok = (
        ctx.phase == "closing"
        and ctx.accepted_contact is not None
        and _norm_contact(ctx.recipient) == _norm_contact(ctx.accepted_contact)
    )
    if not closing_ok:
        if _leaks_address(message, ctx.address):
            v.append("private_address_leak: the address may only go to the accepted vendor after you accept")
        if _leaks_phone(message, ctx.phone):
            v.append("private_phone_leak: the phone may only go to the accepted vendor after you accept")
    price_text = _strip_private(message, ctx.address, ctx.phone) if closing_ok else message

    # Rules 1, 2, 3, 5: every price in the message must be an approved one
    vendor_said = list(ctx.vendor_prices) + ([ctx.vendor_offer] if ctx.vendor_offer is not None else [])
    secret = [ctx.max_price, *ctx.walk_away_prices]

    allowed_exact = list(vendor_said)
    if ctx.counter_price is not None:
        allowed_exact.append(ctx.counter_price)
    if ctx.competing_offer is not None:
        allowed_exact.append(ctx.competing_offer)  # the max-price check below still runs first, so it cannot leak the maximum
    allowed_research = [
        r for r in ctx.research_figures if abs(r - ctx.max_price) > ctx.max_price * NEAR_MAX_FRACTION
    ]  # rule 3: a research figure next to the maximum would give the maximum away

    for mention in extract_prices(price_text, ctx.known_numbers):
        val = mention.value
        if any(_close(val, s) for s in secret) and not any(_close(val, p) for p in vendor_said):
            v.append(f"max_price_leak: '{mention.raw}' reveals your limit")
        elif not (
            any(_close(val, a) for a in allowed_exact) or any(_close(val, r, RESEARCH_TOLERANCE) for r in allowed_research)
        ):
            v.append(f"price_not_allowed: '{mention.raw}' is not the counter, a vendor price or a research figure")

    # Rule 4: the counter itself must follow the rules
    if ctx.counter_price is not None:
        c = ctx.counter_price
        if c <= 0:
            v.append("counter_not_positive")
        if c > ceiling + MONEY_TOLERANCE:
            v.append(f"counter_above_ceiling: {c} > {ceiling}")
        if ctx.vendor_offer is not None and c >= ctx.vendor_offer:
            v.append(f"counter_not_below_vendor_offer: {c} >= {ctx.vendor_offer}")
        if ctx.previous_counter is not None and c < ctx.previous_counter - MONEY_TOLERANCE:
            v.append(f"counter_below_previous: {c} < {ctx.previous_counter}")

    # Rule 7: only cash on delivery
    for term in find_payment_commitments(message):
        v.append(f"payment_not_allowed: '{term}'. Only cash on delivery is allowed")

    return Result(allowed=not v, violations=v)


# ---------- user decisions ----------


@dataclass(frozen=True)
class DealLimits:
    max_price: float
    ceiling_ratio: float = 0.95


@dataclass(frozen=True)
class DecisionResult:
    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""


def check_decision(
    action: str,
    price: float | None,
    deal: DealLimits,
    confirm_over_limit: bool = False,
    actor: Literal["user", "ai"] = "user",
) -> DecisionResult:
    """May this decision go ahead? Going over a limit is the user's right, but only after they confirm."""
    if action == "accept" and actor != "user":
        return DecisionResult(False, reason="Only the user can accept a deal. The AI can only recommend.")

    if action == "reject":
        return DecisionResult(True)

    if action not in ("accept", "counter"):
        return DecisionResult(False, reason=f"Unknown action: {action}")

    if price is None or price <= 0:
        return DecisionResult(False, reason="A price above zero is required.")

    if action == "accept":
        if price <= deal.max_price or confirm_over_limit:
            return DecisionResult(True)
        return DecisionResult(False, True, "This is above your limit. Accept anyway?")

    ceiling = compute_ceiling(deal.max_price, deal.ceiling_ratio)
    if price <= ceiling or confirm_over_limit:
        return DecisionResult(True)
    return DecisionResult(False, True, "This counter will reveal your limit. Send it anyway?")
