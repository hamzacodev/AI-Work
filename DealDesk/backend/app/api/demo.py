"""GET /demo/recorded: one real, saved deal (backend/data/recorded_deal.json). The website offers it as "View a recorded run" when the
daily model budget is used up. It is read-only and never changes. Personal details were replaced with an example address."""

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.agents.runtime import Runtime
from app.api.deals import get_agent_runtime
from app.schemas.deal import Currency

router = APIRouter(tags=["demo"])

RECORDED = Path(__file__).resolve().parents[2] / "data" / "recorded_deal.json"


@router.get("/demo/recorded")
def recorded() -> dict[str, Any]:
    try:
        return json.loads(RECORDED.read_text())
    except (OSError, ValueError) as e:
        raise HTTPException(404, detail={"error": "no_recording", "message": "There is no recorded run on this server."}) from e


Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class HistoryLine(BaseModel):
    sender: Literal["vendor", "agent"]
    text: Line


class DemoChatIn(BaseModel):
    scenario: Literal["xps", "iphone", "sony", "custom"]
    history: list[HistoryLine] = Field(default_factory=list, max_length=20)
    message: Line
    # Only for "custom": the buyer's own request (typed on the page). The maximum comes from the price parser there, never the model.
    item: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""
    max_price: float | None = Field(default=None, gt=0, lt=10_000_000)
    currency: Currency = "USD"
    must_haves: list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)]] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def custom_needs_item_and_maximum(self) -> "DemoChatIn":
        if self.scenario == "custom" and (not self.item or self.max_price is None):
            raise ValueError("a custom chat needs an item and a maximum price")
        return self


class DemoChatOut(BaseModel):
    blocked: bool
    reason: str
    reply: str | None = None
    replies: list[str] = Field(default_factory=list)  # every message the agent sent this turn (it can be two: small talk, then the price)


@router.post("/demo/chat", response_model=DemoChatOut)
async def demo_chat(body: DemoChatIn, runtime: Annotated[Runtime, Depends(get_agent_runtime)]) -> DemoChatOut:
    """The WhatsApp demonstration page: you play the vendor and the real agent answers on a throwaway deal. Nothing is stored or sent."""
    custom = (body.item, body.max_price, body.currency, body.must_haves) if body.scenario == "custom" and body.max_price else None
    result = await runtime.demo_chat(body.scenario, [(h.sender, h.text) for h in body.history], body.message, custom)
    return DemoChatOut(**result)
