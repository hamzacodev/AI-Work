"""POST /trick ("Try to trick it"): see what the agent would do with a message, without changing anything real."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agents.runtime import Runtime
from app.api.deals import get_agent_runtime
from app.schemas.deal import Text

router = APIRouter(tags=["trick"])


class TrickIn(BaseModel):
    deal_id: UUID
    vendor_id: UUID
    message: Text


class TrickOut(BaseModel):
    blocked: bool
    reason: str
    reply: str | None = None  # what the agent would answer. Nothing is sent.


@router.post("/trick", response_model=TrickOut)
async def trick(body: TrickIn, runtime: Annotated[Runtime, Depends(get_agent_runtime)]) -> TrickOut:
    """The message goes through the real Safety Guard, strategy and Negotiator on a throwaway copy of the deal."""
    try:
        return TrickOut(**await runtime.trick(str(body.deal_id), str(body.vendor_id), body.message))
    except KeyError:
        raise HTTPException(status_code=404, detail="Deal or vendor not found") from None
