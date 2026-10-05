import asyncio
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.agents.closer import DecisionError, NeedsConfirmation
from app.agents.runtime import NotYours, Runtime, persona_for
from app.core.config import get_settings
from app.core.db import DealRepo, get_repo
from app.core.queue import VendorQueue, get_queue
from app.core.resume import _spawn, get_processor, resume_pending
from app.negotiation.addons import LABELS, AddonOffer, credit
from app.negotiation.tracker import VendorState, summarize
from app.schemas.deal import (
    ControlIn,
    ControlManyIn,
    ControlManyOut,
    CreateDealResponse,
    DealCreate,
    DealOut,
    DecisionIn,
    FinishIn,
    SummaryOut,
    VendorIn,
    VendorMessageIn,
)

router = APIRouter(prefix="/deals", tags=["deals"])


def get_agent_runtime() -> Runtime:
    """The agent. Only a server that has AGENT_ENABLED=true runs it. Tests replace this function with a fake."""
    if not get_settings().agent_enabled:
        raise HTTPException(status_code=503, detail={"error": "agent_disabled", "message": "The agent is not running on this server."})
    from app.agents.wiring import get_runtime

    return get_runtime()


def maybe_agent_runtime() -> Runtime | None:
    """The agent if this server runs it, otherwise None (the deal is only stored). Tests replace this function."""
    return get_agent_runtime() if get_settings().agent_enabled else None


def build_summary(deal: dict[str, Any]) -> SummaryOut | None:
    """The best deal so far, from the stored vendor rows. Plain code from the Best Offer Tracker."""
    vendors = deal.get("vendors") or []
    if not vendors:
        return None
    research = deal.get("research") or {}
    median = research.get("median") if research.get("available") else None
    def tracker_status(status: str) -> str:
        return "blocked" if status == "blocked" else "negotiating" if status in ("sent", "replied", "negotiating") else "paused"

    values = {k: float(x) for k, x in (deal.get("addon_values") or {}).items()}

    def state(v: dict[str, Any]) -> VendorState:
        offered = [AddonOffer(a["key"], a.get("min_price")) for a in (v.get("addons") or [])]
        value, counted = credit(offered, values, v.get("offer_price"))
        return VendorState(
            v["id"], v["name"], v.get("offer_price"), tracker_status(v["status"]), v.get("stop_reason"), bool(v.get("firm")),  # type: ignore[arg-type]
            credit=value, addons=tuple(LABELS[k] for k in counted),
        )  # fmt: skip

    states = [state(v) for v in vendors]
    s = summarize(states, median, deal["currency"])
    return SummaryOut(
        headline=s.headline,
        best_vendor_id=s.best.vendor_id if s.best else None,
        best_price=s.best.price if s.best else None,
        saved=s.saved,
        saved_pct=s.saved_pct,
        still_negotiating=s.still_negotiating,
        all_done=s.all_done,
        ranking=[
            {
                "vendor_id": r.vendor_id, "name": r.name, "price": r.price, "firm": r.firm, "status": r.status, "stop_reason": r.stop_reason,
                "warning": r.warning, "credit": r.credit, "effective": r.effective, "addons": list(r.addons),
            }
            for r in s.ranking
        ],
        warnings=s.warnings,
    )


def split_vendors(vendors: list[VendorIn], cap: int) -> tuple[list[VendorIn], int]:
    """Removes duplicate contacts, then keeps the first `cap` vendors.

    Returns (accepted vendors, how many were skipped because of the cap).
    Duplicates are dropped silently because they are the same vendor twice.
    """
    seen: set[str] = set()
    unique: list[VendorIn] = []
    for v in vendors:
        key = v.contact.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(v)
    return unique[:cap], max(0, len(unique) - cap)


@router.post("", response_model=CreateDealResponse, status_code=201)
async def create_deal(
    body: DealCreate,
    repo: Annotated[DealRepo, Depends(get_repo)],
    runtime: Annotated[Runtime | None, Depends(maybe_agent_runtime)],
) -> CreateDealResponse:
    accepted, skipped = split_vendors(body.vendors, get_settings().max_vendors_per_deal)

    deal_id = await asyncio.to_thread(  # the database client is synchronous
        repo.create_deal,
        deal={
            "item": body.item,
            "max_price": body.max_price,
            "currency": body.currency,
            "must_haves": body.must_haves,
            "variant": body.variant,
            "alt_variants": body.alt_variants,
            "addon_values": body.addon_values,
            "address": body.address,
            "phone": body.phone,
        },
        vendors=[
            {"name": v.name, "contact": v.contact, "channel": v.channel, "persona": persona_for(i), "played_by": v.played_by}
            for i, v in enumerate(accepted)
        ],
    )
    if runtime is not None:
        # The negotiation takes minutes. The website polls GET /deals/{id} to watch it.
        _spawn(runtime.start_deal(deal_id))
    return CreateDealResponse(id=deal_id, accepted_vendors=len(accepted), skipped_vendors=skipped)


@router.get("/{deal_id}", response_model=DealOut)
async def get_deal(
    deal_id: UUID,
    repo: Annotated[DealRepo, Depends(get_repo)],
    queue: Annotated[VendorQueue, Depends(get_queue)],
) -> DealOut:
    # Typing deal_id as UUID makes FastAPI reject anything else with a 422 before we run.
    # The database client is synchronous, so run it off the event loop.
    deal = await asyncio.to_thread(repo.get_deal, str(deal_id))
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    # Opening a deal also wakes up any vendor of this deal whose work was interrupted.
    if get_processor() is not None:
        await resume_pending(queue, deal_id=str(deal_id))
    out = DealOut.model_validate(deal)
    out.summary = build_summary(deal)
    values = {k: float(x) for k, x in (deal.get("addon_values") or {}).items()}
    for v in out.vendors:  # label the free extras and say which ones count at this vendor's price
        offered = [AddonOffer(a["key"], a.get("min_price")) for a in v.addons if a.get("key") in LABELS]
        counted = set(credit(offered, values, v.offer_price)[1])
        v.addons = [{"key": a.key, "label": LABELS[a.key], "min_price": a.min_price, "counted": a.key in counted} for a in offered]
    return out


@router.post("/{deal_id}/vendors/{vendor_id}/control", response_model=ControlIn)
async def take_control(
    deal_id: UUID, vendor_id: UUID, body: ControlIn, runtime: Annotated[Runtime, Depends(get_agent_runtime)]
) -> ControlIn:
    """Switch one vendor between the simulator and a person. "you" means a person types the vendor's messages."""
    await _vendor_or_404(runtime, str(deal_id), str(vendor_id))
    await runtime.set_played_by(str(deal_id), str(vendor_id), body.played_by)
    return body


@router.post("/{deal_id}/decision")
async def decision(deal_id: UUID, body: DecisionIn, runtime: Annotated[Runtime, Depends(get_agent_runtime)]):
    """The user's decision. Only the user can accept. Above the maximum (or a counter above the ceiling) needs
    `confirm_over_limit`, otherwise 409 with `requires_confirmation`. Contract: CLAUDE.md section 8.1."""
    try:
        await runtime.decide(str(deal_id), str(body.vendor_id), body.action, body.counter_price, body.confirm_over_limit)
    except NeedsConfirmation as e:
        return JSONResponse({"error": "over_limit", "requires_confirmation": True, "message": e.message}, status_code=409)
    except DecisionError as e:
        return JSONResponse({"error": e.code, "requires_confirmation": False, "message": e.message}, status_code=e.status)
    return {"status": "ok"}


@router.post("/{deal_id}/finish")
async def finish_deal(deal_id: UUID, body: FinishIn, runtime: Annotated[Runtime, Depends(get_agent_runtime)]):
    """"stop_and_choose": stop texting every vendor still negotiating. "reject_all": close every vendor. Nothing is sent."""
    try:
        await runtime.finish(str(deal_id), body.action)
    except DecisionError as e:
        return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)
    return {"status": "ok"}


@router.post("/{deal_id}/research/retry", status_code=202)
async def retry_research(deal_id: UUID, runtime: Annotated[Runtime, Depends(get_agent_runtime)]) -> dict[str, bool]:
    """Search the market price again after a failed research. It uses search credits. The agent then continues in the background."""
    try:
        deal = await runtime.store.get(str(deal_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Deal not found") from None
    if deal.research is not None and deal.research.available:
        raise HTTPException(status_code=409, detail={"error": "research_ok", "message": "This deal already has a market price."})
    _spawn(runtime.retry_research(str(deal_id)))
    return {"accepted": True}


@router.post("/{deal_id}/control", response_model=ControlManyOut)
async def take_control_of_many(
    deal_id: UUID, body: ControlManyIn, runtime: Annotated[Runtime, Depends(get_agent_runtime)]
) -> ControlManyOut:
    """Take control of (or hand back) the vendors you choose. Vendors you do not list stay as they are."""
    ids = list(dict.fromkeys(str(v) for v in body.vendor_ids))
    for vendor_id in ids:  # check them all first, so a wrong id changes nothing
        await _vendor_or_404(runtime, str(deal_id), vendor_id)
    for vendor_id in ids:
        await runtime.set_played_by(str(deal_id), vendor_id, body.played_by)
    return ControlManyOut(updated=len(ids), played_by=body.played_by)


@router.post("/{deal_id}/vendors/{vendor_id}/message", status_code=202)
async def vendor_message(
    deal_id: UUID, vendor_id: UUID, body: VendorMessageIn, runtime: Annotated[Runtime, Depends(get_agent_runtime)]
) -> dict[str, bool]:
    """A person typed a message as the vendor ("take control"). The agent answers in the background."""
    v = await _vendor_or_404(runtime, str(deal_id), str(vendor_id))
    if v.played_by != "you":
        raise HTTPException(status_code=409, detail={"error": "not_your_vendor", "message": "Switch this vendor to 'You' before typing as the vendor."})
    _spawn(_run_human_message(runtime, str(deal_id), str(vendor_id), body.text))
    return {"accepted": True}


async def _run_human_message(runtime: Runtime, deal_id: str, vendor_id: str, text: str) -> None:
    try:
        await runtime.human_message(deal_id, vendor_id, text)
    except NotYours:  # the switch was flipped while the message was on its way. Nothing to do.
        return


async def _vendor_or_404(runtime: Runtime, deal_id: str, vendor_id: str):
    try:
        deal = await runtime.store.get(deal_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Deal not found") from None
    v = deal.vendors.get(vendor_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return v
