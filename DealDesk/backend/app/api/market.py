"""POST /market-price: what does this item cost? Used by the Buy form and the Assistant BEFORE a deal starts, so you can choose a
realistic maximum price. It reads the web (a few search credits, cached for 24 hours) and starts nothing. The advice is plain code."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from app.core.config import get_settings
from app.research.market import MarketAdvice, advise
from app.schemas.research import ResearchResult

router = APIRouter(tags=["market"])

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class MarketIn(BaseModel):
    item: Text
    must_haves: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]] = Field(default_factory=list, max_length=10)
    currency: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=3)] = "USD"


async def get_market_lookup():
    """The real lookup. Tests replace this function."""
    from app.agents.wiring import lookup_market

    return lookup_market


@router.post("/market-price", response_model=MarketAdvice)
async def market_price(body: MarketIn, lookup: Annotated[object, Depends(get_market_lookup)]) -> MarketAdvice:
    if not get_settings().agent_enabled:
        raise HTTPException(503, detail={"error": "agent_disabled", "message": "This server does not run the agent, so it cannot check prices."})
    result: ResearchResult = await lookup(body.item, body.must_haves, body.currency.upper())  # type: ignore[operator]
    return advise(result)
