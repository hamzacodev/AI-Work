"""POST /parse-request: turns one sentence into form fields. It reads and fills in. It never starts anything.

The model only reads the words (item, variant, must-haves). Code then keeps only what your own text supports, and the maximum
price comes from the price parser, never from the model. The same reading and checking code as the Assistant chat is used.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StringConstraints

from app.agents.assistant import JsonLLM, read_slots
from app.guardrails.prices import extract_prices

router = APIRouter(tags=["parse"])


class ParseIn(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ParseOut(BaseModel):
    item: str = ""
    variant: str = ""
    max_price: float | None = None
    currency: str = "USD"
    must_haves: list[str] = []
    understood: bool = False  # false when no item could be found in your words
    note: str = ""  # what to check, in plain words


def get_parse_llm() -> JsonLLM:
    """The real model. Tests replace this function."""
    from app.core.llm import get_llm

    return get_llm()  # type: ignore[return-value]


@router.post("/parse-request", response_model=ParseOut)
async def parse_request(body: ParseIn, llm: Annotated[JsonLLM, Depends(get_parse_llm)]) -> ParseOut:
    draft = await read_slots(body.text, llm, "USD", agent="Parse request")
    notes = []
    if not draft.item:
        notes.append("I could not find what you want to buy in that sentence. Fill in the item yourself.")
    if draft.max_price is None:
        found = {p.value for p in extract_prices(body.text)}
        notes.append("I found more than one price, so I left the maximum price empty. Enter it yourself." if len(found) > 1 else "I did not find a maximum price. Enter it yourself.")
    return ParseOut(
        item=draft.item, variant=draft.variant, max_price=draft.max_price, currency=draft.currency, must_haves=draft.must_haves,
        understood=bool(draft.item), note=" ".join(notes) or "Check every field before you start.",
    )  # fmt: skip
