"""Request and response shapes for deals (CLAUDE.md section 8.1).

Pydantic reads incoming JSON and checks it against these classes. If the data
breaks a rule, FastAPI answers 422 and our code never runs. That is why we
describe the rules here, once, instead of writing if-statements in every endpoint.
"""

import re
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.negotiation.addons import BY_KEY, CATALOG

# Text fields are trimmed, must not be empty, and are at most 2,000 characters.
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

Currency = Literal["USD", "PKR", "AED", "GBP", "EUR", "SAR"]
Channel = Literal["email", "chat"]
VendorStatus = Literal["sent", "replied", "negotiating", "paused", "needs_you", "closed", "blocked"]
PlayedBy = Literal["simulator", "you"]

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE = re.compile(r"^\+?[\d\s\-()]{7,20}$")

MAX_VENDORS_IN_REQUEST = 200  # the upload limit. Only the first MAX_VENDORS_PER_DEAL are processed.


def is_valid_contact(value: str) -> bool:
    return bool(_EMAIL.match(value) or _PHONE.match(value))


class VendorIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    contact: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    channel: Channel = "email"
    played_by: PlayedBy = "simulator"  # "you": a person types this vendor's messages. The simulator stays silent for it.

    @field_validator("contact")
    @classmethod
    def contact_must_look_real(cls, v: str) -> str:
        if not is_valid_contact(v):
            raise ValueError("contact must be an email address or a phone number")
        return v


class DealCreate(BaseModel):
    item: Text
    max_price: float = Field(gt=0, lt=1_000_000_000)
    currency: Currency
    must_haves: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=20
    )
    variant: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""  # "black, 128GB"
    alt_variants: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]] = Field(default_factory=list, max_length=10)
    addon_values: dict[str, float] = Field(default_factory=dict, max_length=len(CATALOG))  # what each free extra is worth to you
    address: Text
    phone: str | None = None
    vendors: list[VendorIn] = Field(min_length=1, max_length=MAX_VENDORS_IN_REQUEST)

    @field_validator("addon_values")
    @classmethod
    def addons_must_be_known_and_positive(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = [k for k in v if k not in BY_KEY]
        if unknown:
            raise ValueError(f"unknown add-on: {unknown[0]}. Choose from: {', '.join(BY_KEY)}")
        if any(not (0 <= x <= 1_000_000) for x in v.values()):
            raise ValueError("an add-on value must be between 0 and 1,000,000")
        return {k: x for k, x in v.items() if x > 0}  # a value of 0 means "I do not care about this extra"

    @field_validator("phone")
    @classmethod
    def phone_must_look_real(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not _PHONE.match(v):
            raise ValueError("phone must be a valid phone number")
        return v


class CreateDealResponse(BaseModel):
    id: str
    accepted_vendors: int
    skipped_vendors: int


# ---------- response for GET /deals/{id} ----------


class MessageOut(BaseModel):
    # "from" is a reserved word in Python, so the field is named from_ and
    # exposed as "from" in JSON with an alias.
    model_config = ConfigDict(populate_by_name=True)

    from_: Literal["vendor", "agent", "owner"] = Field(alias="from")
    text: str
    at: str
    simulated: bool = False  # written by a fake vendor


class EventOut(BaseModel):
    agent: str
    text: str
    sources: list[dict[str, Any]] | None = None
    at: str


class VendorOut(BaseModel):
    id: str
    name: str
    channel: Channel
    status: VendorStatus
    offer_price: float | None = None
    recommendation: dict[str, Any] | None = None
    variant_prices: dict[str, float] = {}  # prices the vendor gave for OTHER variants ("gray": 690). Information only.
    addons: list[dict[str, Any]] = []  # free extras the vendor says it gives: {key, label, min_price, counted}
    stop_reason: str | None = None  # why the agent stopped texting (firm_price, round_limit ...)
    firm: bool = False  # the vendor said the price is final
    played_by: PlayedBy = "simulator"
    persona: str | None = None
    messages: list[MessageOut] = []
    events: list[EventOut] = []


class RankedOut(BaseModel):
    vendor_id: str
    name: str
    price: float
    firm: bool
    status: str
    stop_reason: str | None = None
    warning: str | None = None
    credit: float = 0.0  # what the free extras you value are worth to you (your estimate)
    effective: float | None = None  # price minus that. Vendors are ranked on this.
    addons: list[str] = []


class SummaryOut(BaseModel):
    """The best deal so far. The agent only recommends: only the user accepts."""

    headline: str
    best_vendor_id: str | None = None
    best_price: float | None = None
    saved: float | None = None
    saved_pct: float | None = None
    still_negotiating: int
    all_done: bool
    ranking: list[RankedOut] = []
    warnings: list[str] = []


class DecisionIn(BaseModel):
    """The user's decision on one vendor. Only the user can accept (CLAUDE.md rule 7)."""

    vendor_id: UUID
    action: Literal["accept", "counter", "reject"]
    counter_price: float | None = Field(default=None, gt=0, lt=1_000_000_000)
    confirm_over_limit: bool = False


class FinishIn(BaseModel):
    action: Literal["stop_and_choose", "reject_all"]


class ControlIn(BaseModel):
    played_by: PlayedBy


class ControlManyIn(BaseModel):
    """Take control of (or hand back) several vendors at once. Any subset of the deal's vendors."""

    vendor_ids: list[UUID] = Field(min_length=1, max_length=200)
    played_by: PlayedBy


class ControlManyOut(BaseModel):
    updated: int
    played_by: PlayedBy


class VendorMessageIn(BaseModel):
    text: Text


class DealOut(BaseModel):
    """Note what is NOT here: address and phone. They never leave the server in this response."""

    id: str
    item: str
    max_price: float
    currency: Currency
    status: str
    research: dict[str, Any] | None = None
    variant: str = ""
    alt_variants: list[str] = []
    addon_values: dict[str, float] = {}
    accepted_vendor_id: str | None = None  # set when the user accepted a vendor
    accepted_price: float | None = None
    summary: SummaryOut | None = None
    vendors: list[VendorOut] = []
