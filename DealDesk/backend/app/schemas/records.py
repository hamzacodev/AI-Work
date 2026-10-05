"""The records the Manager works on, and the stores that keep them.

DealRecord and VendorRecord are the agent's working copy of one deal. A DealStore loads and saves them.
  InMemoryDealStore  : tests and the terminal chat. Forgotten when the program stops.
  SupabaseDealStore  : the real one (app/core/db.py). It is what lets a restart resume a negotiation.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.agents.fact_rules import Turn
from app.negotiation.addons import AddonOffer
from app.negotiation.strategy import Recommendation
from app.negotiation.tactics import Tactics
from app.schemas.research import ResearchResult

VendorStatus = Literal["negotiating", "paused", "needs_you", "blocked", "closed"]  # closed = the deal is decided, no more messages
PlayedBy = Literal["simulator", "you"]  # who writes this vendor's messages: a fake vendor, or the person using the app


@dataclass
class Event:
    agent: str
    text: str
    sources: list[dict] = field(default_factory=list)


@dataclass
class VendorRecord:
    vendor_id: str
    name: str
    contact: str
    status: VendorStatus = "negotiating"
    stop_reason: str | None = None
    offer: float | None = None  # the vendor's latest verified price
    offers_so_far: list[float] = field(default_factory=list)
    last_counter: float | None = None
    rounds: int = 0  # messages with a counter or a leverage line that we sent
    stall_count: int = 0
    firm: bool = False
    firm_pushes: int = 0
    last_leverage: float | None = None
    recommendation: Recommendation | None = None
    conversation: list[Turn] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    variant_prices: dict[str, float] = field(default_factory=dict)  # prices the vendor gave for OTHER variants ("gray": 690)
    addons: list[AddonOffer] = field(default_factory=list)  # free extras the vendor says it gives
    persona: str | None = None  # the fake vendor's personality (simulator only)
    played_by: PlayedBy = "simulator"


@dataclass
class DealRecord:
    id: str
    item: str
    max_price: float  # private: only the code checkers see it, never a prompt
    currency: str = "USD"
    must_haves: list[str] = field(default_factory=list)
    address: str = ""  # private until the user accepts
    phone: str | None = None
    vendors: dict[str, VendorRecord] = field(default_factory=dict)
    research: ResearchResult | None = None
    tactics: Tactics = field(default_factory=Tactics)
    variant: str = ""  # the color, size or storage the buyer wants: "black, 128GB"
    alt_variants: list[str] = field(default_factory=list)  # other variants the buyer would accept
    addon_values: dict[str, float] = field(default_factory=dict)  # what each free extra is worth to the buyer (the buyer's estimate)
    status: str = "negotiating"  # negotiating, accepted, rejected
    accepted_vendor_id: str | None = None
    accepted_price: float | None = None
    max_rounds: int = 3
    ceiling_ratio: float = 0.95

    @property
    def full_item(self) -> str:
        """The item with the wanted variant, for research and for messages: "iPhone 15 (black, 128GB)"."""
        return f"{self.item} ({self.variant})" if self.variant else self.item


@dataclass(frozen=True)
class Outbound:
    """A message the agent sent. The channel (terminal, simulator) delivers it."""

    deal_id: str
    vendor_id: str
    text: str
    action: str
    counter_price: float | None = None
    leverage_price: float | None = None
    followup: str | None = None  # a second message sent right after this one (small talk, then back to the price)


class DealStore(Protocol):
    async def get(self, deal_id: str) -> DealRecord: ...

    async def save(self, deal: DealRecord) -> None: ...


class InMemoryDealStore:
    """For tests and the terminal chat. The state is lost when the program stops."""

    def __init__(self) -> None:
        self.deals: dict[str, DealRecord] = {}
        self.saves = 0

    def add(self, deal: DealRecord) -> None:
        self.deals[deal.id] = deal

    async def get(self, deal_id: str) -> DealRecord:
        return self.deals[deal_id]

    async def save(self, deal: DealRecord) -> None:
        self.deals[deal.id] = deal
        self.saves += 1
