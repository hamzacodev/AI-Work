"""A per-visitor rate limit (CLAUDE.md section 8.1).

A sliding window: each visitor may make `limit` requests in any `window` seconds.
It is kept in memory, so on a host that runs several copies each copy counts alone.
That is fine for a demo. The daily model budget (budget.py) is the real cost guard.
"""

import time
from collections import deque
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

MAX_TRACKED_VISITORS = 10_000


class SlidingWindowLimiter:
    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> tuple[bool, float]:
        """Returns (allowed, seconds to wait). A refused request is not counted."""
        now = self.clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False, max(0.0, self.window - (now - hits[0]))
        hits.append(now)
        if len(self._hits) > MAX_TRACKED_VISITORS:
            self._forget_idle(now)
        return True, 0.0

    def _forget_idle(self, now: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window]:
            del self._hits[key]


def client_ip(request: Request, header: str = "") -> str:
    """The visitor's address. Behind Cloudflare the real address is in a header Cloudflare sets itself."""
    if header and (value := request.headers.get(header)):
        return value.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Writes (POST) get `write_limit` a minute. Reads (GET) get four times that, because the
    deal page asks for updates every 3 seconds. /health and CORS preflights are never limited."""

    def __init__(self, app, write_limit: int, ip_header: str = "", clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(app)
        self.write = SlidingWindowLimiter(write_limit, clock=clock)
        self.read = SlidingWindowLimiter(write_limit * 4, clock=clock)
        self.ip_header = ip_header

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path == "/health":
            return await call_next(request)
        limiter = self.write if request.method != "GET" else self.read
        allowed, wait = limiter.check(client_ip(request, self.ip_header))
        if not allowed:
            seconds = int(wait) + 1
            return JSONResponse(
                {"error": "rate_limited", "message": "Too many requests. Please slow down.", "retry_after": seconds},
                status_code=429,
                headers={"Retry-After": str(seconds)},
            )
        return await call_next(request)
