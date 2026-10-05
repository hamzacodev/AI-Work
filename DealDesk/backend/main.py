import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    assistant,
    deals,
    demo,
    health,
    market,
    parse,
    reset,
    scorecard,
    trick,
    usage,
)
from app.core.config import get_settings
from app.core.llm import BudgetExhausted, BudgetUnavailable
from app.core.queue import get_queue
from app.core.ratelimit import RateLimitMiddleware
from app.core.resume import get_processor, resume_pending

settings = get_settings()
log = logging.getLogger("dealdesk")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # On start, pick up any vendor whose work was cut off by a restart. Does nothing until
    # an agent processor is registered (Phase 3).
    if settings.agent_enabled and get_processor() is None:
        from app.agents.wiring import get_runtime
        from app.core.resume import set_processor

        set_processor(get_runtime().resume_vendor)  # the agent finishes interrupted work after a restart
    if get_processor() is not None:
        try:
            await resume_pending(get_queue())
        except Exception:
            log.exception("resume at startup failed")
    yield


app = FastAPI(title="DealDesk API", lifespan=lifespan)

# Order matters. Middleware added LATER wraps the earlier ones, so CORS is added last and is the
# outermost layer. That way even a 429 from the rate limiter carries the CORS headers the browser needs.
app.add_middleware(
    RateLimitMiddleware,
    write_limit=settings.rate_limit_per_minute,
    ip_header=settings.client_ip_header,
)
# Only the origins listed in ALLOWED_ORIGINS may call the API from a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(BudgetExhausted)
async def budget_exhausted(_: Request, exc: BudgetExhausted) -> JSONResponse:
    # The frontend shows "Demo limit reached" and offers the recorded run.
    return JSONResponse({"error": "budget_exhausted", "message": str(exc), "reason": exc.reason}, status_code=429)


@app.exception_handler(BudgetUnavailable)
async def budget_unavailable(_: Request, exc: BudgetUnavailable) -> JSONResponse:
    return JSONResponse({"error": "budget_unavailable", "message": "The service is busy. Try again soon."}, status_code=503)


app.include_router(health.router)
app.include_router(deals.router)
app.include_router(assistant.router)
app.include_router(trick.router)
app.include_router(usage.router)
app.include_router(reset.router)
app.include_router(market.router)
app.include_router(demo.router)
app.include_router(parse.router)
app.include_router(scorecard.router)

