import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.core.ratelimit import (
    MAX_TRACKED_VISITORS,
    RateLimitMiddleware,
    SlidingWindowLimiter,
)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ---------------------------------------------------------------- the limiter


def test_allows_up_to_the_limit_then_refuses():
    lim = SlidingWindowLimiter(3, 60, Clock())
    assert [lim.check("a")[0] for _ in range(4)] == [True, True, True, False]


def test_visitors_are_counted_separately():
    lim = SlidingWindowLimiter(1, 60, Clock())
    assert lim.check("a")[0] and lim.check("b")[0]
    assert not lim.check("a")[0]


def test_the_window_slides():
    clock = Clock()
    lim = SlidingWindowLimiter(2, 60, clock)
    lim.check("a")
    clock.t += 30
    lim.check("a")
    assert not lim.check("a")[0]
    clock.t += 31  # the first hit is now older than 60 seconds
    assert lim.check("a")[0]


def test_it_says_how_long_to_wait_and_a_refusal_is_not_counted():
    clock = Clock()
    lim = SlidingWindowLimiter(1, 60, clock)
    lim.check("a")
    clock.t += 20
    ok, wait = lim.check("a")
    assert not ok and 39 < wait <= 40
    for _ in range(5):
        lim.check("a")  # hammering does not push the wait further out
    clock.t += 41
    assert lim.check("a")[0]


def test_idle_visitors_are_forgotten_so_memory_stays_small():
    clock = Clock()
    lim = SlidingWindowLimiter(5, 60, clock)
    for i in range(MAX_TRACKED_VISITORS + 5):
        lim.check(f"ip-{i}")
    clock.t += 120
    lim.check("new")
    assert len(lim._hits) < 100


# ---------------------------------------------------------------- the middleware


def make_app(write_limit=3, ip_header="", clock=None):
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/thing")
    def get_thing():
        return {"ok": True}

    @app.post("/thing")
    def post_thing():
        return {"ok": True}

    kwargs = {"write_limit": write_limit, "ip_header": ip_header}
    if clock:
        kwargs["clock"] = clock
    app.add_middleware(RateLimitMiddleware, **kwargs)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:4000"], allow_methods=["*"], allow_headers=["*"])
    return TestClient(app)


def test_the_fourth_write_in_a_minute_is_refused_with_429():
    c = make_app(3)
    assert [c.post("/thing").status_code for _ in range(3)] == [200, 200, 200]
    r = c.post("/thing")
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "rate_limited" and body["retry_after"] >= 1
    assert int(r.headers["retry-after"]) >= 1


def test_reads_get_four_times_the_limit():
    c = make_app(3)
    assert all(c.get("/thing").status_code == 200 for _ in range(12))
    assert c.get("/thing").status_code == 429


def test_reads_and_writes_have_separate_counters():
    c = make_app(2)
    for _ in range(2):
        c.post("/thing")
    assert c.post("/thing").status_code == 429
    assert c.get("/thing").status_code == 200


def test_health_is_never_limited():
    c = make_app(1)
    assert all(c.get("/health").status_code == 200 for _ in range(50))


def test_cors_preflight_is_never_limited():
    c = make_app(1)
    headers = {"Origin": "http://localhost:4000", "Access-Control-Request-Method": "POST"}
    assert all(c.options("/thing", headers=headers).status_code == 200 for _ in range(10))


def test_the_429_still_carries_the_cors_header_so_the_browser_can_read_it():
    c = make_app(1)
    c.post("/thing")
    r = c.post("/thing", headers={"Origin": "http://localhost:4000"})
    assert r.status_code == 429
    assert r.headers["access-control-allow-origin"] == "http://localhost:4000"


def test_visitors_are_told_apart_by_the_cloudflare_header():
    c = make_app(1, ip_header="cf-connecting-ip")
    assert c.post("/thing", headers={"cf-connecting-ip": "1.1.1.1"}).status_code == 200
    assert c.post("/thing", headers={"cf-connecting-ip": "1.1.1.1"}).status_code == 429
    assert c.post("/thing", headers={"cf-connecting-ip": "2.2.2.2"}).status_code == 200


def test_without_the_header_the_connection_address_is_used():
    c = make_app(1, ip_header="cf-connecting-ip")
    assert c.post("/thing").status_code == 200
    assert c.post("/thing").status_code == 429


def test_the_limit_resets_after_a_minute():
    clock = Clock()
    c = make_app(1, clock=clock)
    assert c.post("/thing").status_code == 200
    assert c.post("/thing").status_code == 429
    clock.t += 61
    assert c.post("/thing").status_code == 200


def test_the_real_app_has_the_limiter_inside_cors():
    from main import app

    kinds = [m.cls for m in app.user_middleware]  # the first one is the outermost
    assert RateLimitMiddleware in kinds and CORSMiddleware in kinds
    assert kinds.index(CORSMiddleware) < kinds.index(RateLimitMiddleware)


@pytest.mark.parametrize("limit", [1, 5, 30])
def test_the_limit_is_exact(limit):
    c = make_app(limit)
    codes = [c.post("/thing").status_code for _ in range(limit + 2)]
    assert codes.count(200) == limit and codes.count(429) == 2
