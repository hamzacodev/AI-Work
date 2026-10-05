"""The Assistant chat: one conversation that never closes (see app/agents/assistant.py)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StringConstraints

from app.agents.assistant import AssistantDeps, AssistantState, ChatMessage, handle
from app.core.config import get_settings
from app.core.resume import _spawn

router = APIRouter(prefix="/assistant", tags=["assistant"])


class MessageIn(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ChatOut(BaseModel):
    messages: list[ChatMessage]
    draft: dict | None = None  # the purchase being prepared, if any
    awaiting: str = "none"  # none, max_price (waiting for your budget) or confirm (waiting for your yes)


def get_assistant() -> AssistantDeps:
    """The real Assistant: the real model, the database and the agent. Tests replace this function."""
    from app.agents.wiring import get_runtime, lookup_market
    from app.core.db import SupabaseAssistantStore, get_client, get_repo
    from app.core.llm import get_llm

    on = get_settings().agent_enabled
    start = get_runtime().start_deal if on else None
    return AssistantDeps(
        llm=get_llm(), store=SupabaseAssistantStore(get_client()), repo=get_repo(), start_deal=start, spawn=_spawn,  # type: ignore[arg-type]
        market=lookup_market if on else None,
    )


def _out(state: AssistantState, messages: list[ChatMessage]) -> ChatOut:
    return ChatOut(messages=messages, draft=state.draft.model_dump() if state.draft else None, awaiting=state.awaiting)


@router.get("", response_model=ChatOut)
async def read_chat(deps: Annotated[AssistantDeps, Depends(get_assistant)]) -> ChatOut:
    state, messages = await deps.store.load()
    return _out(state, messages)


@router.post("/message", response_model=ChatOut)
async def send_message(body: MessageIn, deps: Annotated[AssistantDeps, Depends(get_assistant)]) -> ChatOut:
    """You write. The Assistant answers, and starts a new purchase when you ask for one and confirm it."""
    state, messages = await handle(body.text, deps)
    return _out(state, messages)
