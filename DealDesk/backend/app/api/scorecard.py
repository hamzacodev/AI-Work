"""GET /scorecard: the latest stored evaluation run for each mode. Only real, stored runs. Nothing is computed or invented here."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.db import get_eval_store, latest_per_mode

router = APIRouter(tags=["scorecard"])


@router.get("/scorecard")
def scorecard(store: Annotated[Any, Depends(get_eval_store)]) -> dict[str, list[dict]]:
    try:
        runs = store.runs()
    except Exception:  # noqa: BLE001  (a database problem shows an empty scorecard, never an invented one)
        runs = []
    return {"runs": latest_per_mode(runs)}
