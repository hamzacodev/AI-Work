"""GET /usage: how many tokens the model calls of this server run used, by agent. Counts only, no prompts and no answers."""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter

from app.core.llm import usage_log

router = APIRouter(tags=["usage"])


@router.get("/usage")
def usage(recent: int = 20) -> dict[str, Any]:
    recent = max(0, min(recent, 200))
    return {**usage_log.summary(), "recent": [asdict(r) for r in list(usage_log.records)[-recent:]] if recent else []}
