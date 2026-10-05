"""What happened in one evaluated deal, as plain data. Metrics and the rubric are computed from this and nothing else."""

from dataclasses import dataclass, field

from app.evals.scenarios import Scenario


@dataclass
class VendorTranscript:
    name: str
    persona: str
    messages: list[tuple[str, str]] = field(default_factory=list)  # (sender, text) in order. sender: vendor or agent
    offers_read: list[float] = field(default_factory=list)  # the prices the agent understood, in order (protected mode)
    blocked: bool = False
    events: list[str] = field(default_factory=list)  # the agent's own timeline lines (protected mode)
    agent_accepted_at: float | None = None  # the agent acted alone and accepted (the unprotected baseline can do this)
    rounds: int = 0
    firm_pushes: int = 0
    closing_index: int | None = None  # the position of the closing message in `messages` (it may carry the address)

    def agent_texts(self) -> list[str]:
        return [t for s, t in self.messages if s == "agent"]

    def vendor_texts(self) -> list[str]:
        return [t for s, t in self.messages if s == "vendor"]


@dataclass
class DealTranscript:
    scenario: Scenario
    mode: str  # safety_on or safety_off
    vendors: list[VendorTranscript] = field(default_factory=list)
    accepted_vendor: int | None = None
    accepted_price: float | None = None
    accepted_by: str | None = None  # "owner" (the scripted owner) or "agent" (the agent alone)
    opening_price: float | None = None  # the accepted vendor's first price
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    error: str = ""
