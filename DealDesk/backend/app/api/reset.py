"""POST /admin/reset: wipe every deal and chat, for testing only. Off unless ALLOW_RESET=true (the public API must not be able to do this)."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings

router = APIRouter(tags=["admin"])

# Children first. The research cache, evaluation runs and usage counters are kept.
TABLES = ["assistant_messages", "assistant_threads", "events", "messages", "vendors", "deals"]
NIL_ID = "00000000-0000-0000-0000-000000000000"


def _wipe() -> None:
    from app.core.db import get_client

    client = get_client()
    for t in TABLES:
        client.table(t).delete().neq("id", NIL_ID).execute()


@router.post("/admin/reset")
async def reset_everything() -> dict[str, Any]:
    if not get_settings().allow_reset:
        raise HTTPException(status_code=403, detail={"error": "reset_disabled", "message": "Reset is off on this server (ALLOW_RESET=false)."})
    await asyncio.to_thread(_wipe)
    if get_settings().agent_enabled:  # forget the deals kept in memory
        from app.agents.wiring import get_runtime

        store = get_runtime().store
        for name in ("_cache", "_snap"):
            getattr(store, name, {}).clear()
    return {"status": "ok", "cleared": TABLES}
