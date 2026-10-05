"""Currency conversion with free exchange-rate sources that need no key (CLAUDE.md section 11).

Order: open.er-api.com, then the jsDelivr currency-api, then a table built into the code with its date.
Rates are cached for a day. A live rate that is wildly different from the built-in table is rejected,
because a glitch in a free API must never turn $700 into $7.
"""

import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import Literal

import httpx
from pydantic import BaseModel

log = logging.getLogger("dealdesk.fx")

SUPPORTED = ("USD", "PKR", "AED", "GBP", "EUR", "SAR")

FALLBACK_AS_OF = "2026-10-01"
FALLBACK_RATES = {"USD": 1.0, "PKR": 276.98, "AED": 3.6725, "GBP": 0.7538, "EUR": 0.8818, "SAR": 3.75}  # units per 1 USD

TTL_LIVE = 24 * 3600.0
TTL_FALLBACK = 15 * 60.0  # try the live sources again soon
SANITY_RANGE = (0.5, 2.0)  # a live rate must be within this factor of the built-in table


class UnsupportedCurrency(ValueError):
    pass


class RateTable(BaseModel):
    rates: dict[str, float]  # units of each currency per 1 USD
    as_of: str
    source: Literal["live", "fallback"]
    origin: str

    def describe(self) -> str:
        if self.source == "live":
            return f"Exchange rates from {self.origin} as of {self.as_of}."
        return f"Exchange rates are approximate (built-in table of {self.as_of}), because live rates were unavailable."


Fetcher = Callable[[], Awaitable[RateTable]]


def fallback_table() -> RateTable:
    return RateTable(rates=dict(FALLBACK_RATES), as_of=FALLBACK_AS_OF, source="fallback", origin="built-in table")


def _validated(rates: dict[str, float], as_of: str, origin: str) -> RateTable:
    out: dict[str, float] = {}
    for cur in SUPPORTED:
        v = rates.get(cur)
        if not isinstance(v, int | float) or not math.isfinite(v) or v <= 0:
            raise ValueError(f"{origin}: missing or invalid rate for {cur}")
        low, high = SANITY_RANGE
        if not (FALLBACK_RATES[cur] * low <= v <= FALLBACK_RATES[cur] * high):
            raise ValueError(f"{origin}: rate for {cur} ({v}) looks wrong")
        out[cur] = float(v)
    return RateTable(rates=out, as_of=as_of, source="live", origin=origin)


async def fetch_open_er_api() -> RateTable:
    async with httpx.AsyncClient(timeout=6) as c:
        d = (await c.get("https://open.er-api.com/v6/latest/USD")).json()
    if d.get("result") != "success":
        raise ValueError("open.er-api.com did not return success")
    return _validated(d["rates"], str(d.get("time_last_update_utc", ""))[:16], "open.er-api.com")


async def fetch_currency_api() -> RateTable:
    async with httpx.AsyncClient(timeout=6) as c:
        d = (await c.get("https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json")).json()
    rates = {k.upper(): v for k, v in d["usd"].items() if k.upper() in SUPPORTED}
    return _validated(rates, str(d.get("date", "")), "jsDelivr currency-api")


class FxService:
    def __init__(self, fetchers: tuple[Fetcher, ...] = (fetch_open_er_api, fetch_currency_api), clock=time.time) -> None:
        self.fetchers = fetchers
        self.clock = clock
        self._table: RateTable | None = None
        self._expires = 0.0

    async def table(self) -> RateTable:
        if self._table is not None and self.clock() < self._expires:
            return self._table
        for fetch in self.fetchers:
            try:
                self._table = await fetch()
                self._expires = self.clock() + TTL_LIVE
                return self._table
            except Exception as e:  # noqa: BLE001 - any failure of a free source means: try the next one
                log.warning("exchange-rate source failed: %s", e)
        self._table = fallback_table()
        self._expires = self.clock() + TTL_FALLBACK
        return self._table


def convert(amount: float, src: str, dst: str, table: RateTable) -> float:
    src, dst = src.upper(), dst.upper()
    if src not in table.rates or dst not in table.rates:
        raise UnsupportedCurrency(f"Cannot convert {src} to {dst}")
    return amount / table.rates[src] * table.rates[dst]
