"""The shapes the Researcher returns (CLAUDE.md section 11)."""

from typing import Literal

from pydantic import BaseModel

Confidence = Literal["low", "medium", "high"]


class Source(BaseModel):
    title: str
    url: str
    price: float  # in the result's currency
    region: str
    seller: str = ""


class ResearchResult(BaseModel):
    currency: str
    low: float | None = None
    median: float | None = None
    high: float | None = None
    n_sources: int = 0  # distinct websites
    regions: list[str] = []
    confidence: Confidence = "low"
    sources: list[Source] = []
    note: str = ""
    available: bool = False  # false when no usable price was found, or research could not run
    reason: str = ""  # why it is unavailable, or why confidence is low
    queries: list[str] = []
    credits_used: int = 0
    outliers_removed: int = 0
    from_cache: bool = False
    researched_at: str = ""
    fx_note: str = ""
