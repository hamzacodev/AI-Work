"""The Researcher: finds the real market price of an item, with sources (CLAUDE.md section 11).

Who does what:
    code    builds the searches, converts currencies, removes outliers, does all the math
    Tavily  searches the web
    model   reads the item name, and reads prices off the search results (every price is verified by code)

It runs once per deal and its result is cached. If research cannot be done (search down, credits used up,
no usable price) it says so plainly. It NEVER invents a figure, and the agent then asks the user.
"""

import asyncio
import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel

from app.core.llm import UNTRUSTED_NOTICE, LLMError, llm_label, untrusted
from app.core.money import format_price
from app.research import pricing
from app.research.extract import RawOffer, extract_offers
from app.research.fx import FxService, UnsupportedCurrency, convert
from app.research.search import (
    SearchBudget,
    SearchBudgetExhausted,
    SearchError,
    SearchProvider,
)
from app.schemas.research import ResearchResult, Source

log = logging.getLogger("dealdesk.researcher")

MAX_QUERIES = 6  # also the most credits one deal can use
MAX_RESULTS = 5
DEFAULT_REGIONS = ("USA", "UK", "UAE")
CACHE_HOURS = 24

NOTE = "Reference price converted to {cur}. Import tax, shipping and local margins are not included."

# the buyer's own country, taken from the currency (name for the query, name for Tavily's country option)
HOME = {
    "USD": ("USA", "united states"),
    "PKR": ("Pakistan", "pakistan"),
    "AED": ("UAE", "united arab emirates"),
    "GBP": ("UK", "united kingdom"),
    "EUR": ("Europe", "germany"),
    "SAR": ("Saudi Arabia", "saudi arabia"),
}
COUNTRY_OPTION = {"USA": "united states", "UK": "united kingdom", "UAE": "united arab emirates"}


class JsonLLM(Protocol):
    async def complete_json(self, role: str, system: str, user: str, schema: type, deal_id: str | None = None): ...


# ---------------------------------------------------------------- the cache


class ResearchCache(Protocol):
    def get(self, key: str, max_age_seconds: float) -> dict | None: ...

    def put(self, key: str, result: dict) -> None: ...


class MemoryResearchCache:
    def __init__(self, clock=lambda: datetime.now(UTC)) -> None:
        self.clock = clock
        self.data: dict[str, tuple[datetime, dict]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, max_age_seconds: float) -> dict | None:
        with self._lock:
            hit = self.data.get(key)
        if hit and self.clock() - hit[0] <= timedelta(seconds=max_age_seconds):
            return hit[1]
        return None

    def put(self, key: str, result: dict) -> None:
        with self._lock:
            self.data[key] = (self.clock(), result)


class SupabaseResearchCache:
    def __init__(self, client) -> None:
        self.db = client

    def get(self, key: str, max_age_seconds: float) -> dict | None:
        since = (datetime.now(UTC) - timedelta(seconds=max_age_seconds)).isoformat().replace("+00:00", "Z")
        rows = self.db.table("research_cache").select("result").eq("key", key).gte("created_at", since).limit(1).execute().data
        return rows[0]["result"] if rows else None

    def put(self, key: str, result: dict) -> None:
        self.db.table("research_cache").upsert(
            {"key": key, "result": result, "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z")}
        ).execute()


def cache_key(item: str, must_haves: list[str], currency: str, regions: tuple[str, ...]) -> str:
    norm = {
        "item": re.sub(r"\s+", " ", item.strip().lower()),
        "must": sorted(re.sub(r"\s+", " ", m.strip().lower()) for m in must_haves),
        "cur": currency.upper(),
        "regions": sorted(regions),
    }
    return hashlib.sha256(json.dumps(norm, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------- step 1: understand the item


class ItemSpec(BaseModel):
    brand: str = ""
    model: str = ""
    specs: list[str] = []
    condition: Literal["new", "used", "refurbished"] = "new"


_NORMALIZE_PROMPT = f"""You read what a buyer wants to buy and pull out the product details so it can be searched on the web.
{UNTRUSTED_NOTICE}
Return: brand, model (the product name and number), specs (up to 3 key specs the buyer asked for, such as 16GB RAM),
and condition (new unless the buyer clearly wants used or refurbished). Do not invent details that are not in the text."""


async def normalize_item(item: str, must_haves: list[str], llm: JsonLLM, deal_id: str | None) -> ItemSpec:
    """Not critical: if the model fails, the buyer's own words are used."""
    want = f"Item: {item}. Required features: {', '.join(must_haves) or 'none'}."
    try:
        with llm_label("Researcher", "normalize the item name for searching"):
            spec = await llm.complete_json("fast", _NORMALIZE_PROMPT, untrusted("buyer_request", want), ItemSpec, deal_id)
    except LLMError:
        return ItemSpec()
    return spec


def core_query(item: str, spec: ItemSpec) -> str:
    """The words to search for. Falls back to the buyer's own text if the model's version looks unrelated."""
    candidate = " ".join(p for p in [spec.brand, spec.model, *spec.specs[:2]] if p).strip()
    overlap = {t for t in re.findall(r"[a-z0-9]+", candidate.lower())} & {t for t in re.findall(r"[a-z0-9]+", item.lower())}
    text = candidate if candidate and overlap else item
    return re.sub(r"\s+", " ", text)[:120].strip()


# ---------------------------------------------------------------- step 2: the searches


@dataclass(frozen=True)
class Query:
    text: str
    region: str
    country: str | None


def build_queries(core: str, currency: str, regions: tuple[str, ...] = DEFAULT_REGIONS) -> list[Query]:
    home_name, home_country = HOME.get(currency.upper(), ("USA", "united states"))
    queries = [Query(f"{core} price", "Global", None), Query(f"{core} price {home_name}", home_name, home_country)]
    for r in regions:
        if r != home_name:
            queries.append(Query(f"{core} price {r}", r, COUNTRY_OPTION.get(r)))
    queries.append(Query(f"{core} new vs refurbished price", "Global", None))
    return queries[:MAX_QUERIES]


# ---------------------------------------------------------------- the whole job


@dataclass
class ResearchDeps:
    llm: JsonLLM
    search: SearchProvider
    fx: FxService
    budget: SearchBudget
    cache: ResearchCache | None = None


async def _search_and_read(q: Query, item_text: str, must_haves: list[str], deps: ResearchDeps, deal_id: str | None):
    """One search and one model read. Returns (offers, credits used) or raises."""
    await deps.budget.consume(1)  # count the credit BEFORE searching
    hits = await deps.search.search(q.text, q.country, MAX_RESULTS)
    offers = await extract_offers(hits, item_text, must_haves, deps.llm, deal_id)  # type: ignore[arg-type]
    return offers


def broad_core(item: str, spec: ItemSpec) -> str:
    """The base model only (brand and model, or the first 3 words), for the second, broader search."""
    text = " ".join(p for p in [spec.brand, spec.model] if p).strip() or " ".join(item.split()[:3])
    return re.sub(r"\s+", " ", text)[:60].strip()


async def _collect(queries, item_text, must_haves, deps, deal_id, currency, table):
    """Runs the searches and the reading, converts to the buyer's currency. Returns (offers, credits used, failures)."""
    outcomes = await asyncio.gather(*[_search_and_read(q, item_text, must_haves, deps, deal_id) for q in queries], return_exceptions=True)
    found: list[tuple[Query, RawOffer]] = []
    credits = 0
    failures: list[str] = []
    for q, out in zip(queries, outcomes, strict=True):
        if isinstance(out, SearchBudgetExhausted):
            failures.append("the monthly search limit was reached")
        elif isinstance(out, SearchError):
            credits += 1
            failures.append("a search failed")
        elif isinstance(out, LLMError):
            credits += 1
            failures.append("a result could not be read")
        elif isinstance(out, BaseException):
            log.exception("research query failed", exc_info=out)
            failures.append("an unexpected error occurred")
        else:
            credits += 1
            found.extend((q, o) for o in out)
    offers: list[pricing.Offer] = []
    for q, o in found:
        try:
            price = convert(o.price, o.currency, currency, table)
        except UnsupportedCurrency:
            continue
        offers.append(pricing.Offer(round(price, 2), o.url, o.title, q.region, o.seller, o.condition))
    return offers, credits, failures


async def research(
    item: str,
    must_haves: list[str],
    currency: str,
    deps: ResearchDeps,
    deal_id: str | None = None,
    regions: tuple[str, ...] = DEFAULT_REGIONS,
) -> ResearchResult:
    currency = currency.upper()
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    key = cache_key(item, must_haves, currency, regions)

    if deps.cache is not None:
        cached = await asyncio.to_thread(deps.cache.get, key, CACHE_HOURS * 3600)
        if cached:
            return ResearchResult(**{**cached, "from_cache": True, "credits_used": 0})

    spec = await normalize_item(item, must_haves, deps.llm, deal_id)
    queries = build_queries(core_query(item, spec), currency, regions)
    item_text = " ".join([item, *must_haves])

    table = await deps.fx.table()
    offers, credits, failures = await _collect(queries, item_text, must_haves, deps, deal_id, currency, table)

    # Nothing matched every spec the buyer wrote (for example a spec combination that does not exist, or two RAM sizes): search again
    # for the base model only (up to 2 more credits, never more than MAX_QUERIES in total). The result is marked low confidence, so the agent does not quote it as fact.
    broad_used = False
    if not pricing.clean_offers(offers, spec.condition) and not any("limit" in f for f in failures):
        base = broad_core(item, spec)
        room = min(2, MAX_QUERIES - credits)  # one deal never uses more than MAX_QUERIES credits in total
        if base and room > 0 and base.lower() != core_query(item, spec).lower():
            more, extra, more_failures = await _collect(build_queries(base, currency, regions)[:room], base, [], deps, deal_id, currency, table)
            offers, credits, failures, broad_used = offers + more, credits + extra, failures + more_failures, bool(more)

    want_condition = spec.condition
    kept, dropped = pricing.remove_outliers(pricing.clean_offers(offers, want_condition))
    stats = pricing.compute(kept)
    grouped = False
    if stats is not None and stats.spread > pricing.BIG_SPREAD:
        # The prices disagree (often several generations of the same item): keep the biggest group of similar prices.
        group, rest = pricing.densest_group(kept)
        if rest:
            kept, dropped, grouped = group, dropped + rest, True
            stats = pricing.compute(kept)

    base = {
        "currency": currency,
        "queries": [q.text for q in queries],
        "credits_used": credits,
        "researched_at": now,
        "fx_note": table.describe(),
        "note": NOTE.format(cur=currency),
    }
    if stats is None:
        reason = "No usable prices were found." if not failures else "Research could not be completed: " + "; ".join(sorted(set(failures))) + "."
        return ResearchResult(**base, available=False, confidence="low", reason=reason)

    reason = ""
    confidence = "low" if broad_used else stats.confidence
    if broad_used:
        reason = (
            "No page matched every detail you wrote (for example two different RAM sizes, or a spec that does not exist), so this is the "
            "range for the base model only. Check the details and name the exact model."
        )
    elif stats.confidence == "low":
        if stats.spread > pricing.BIG_SPREAD:
            reason = (
                "The prices vary a lot, which usually means the item name is too general "
                "(for example several generations of the same laptop). Name the exact model to get a trustworthy range."
            )
        else:
            reason = "Too few sources to trust this range."
    elif grouped:
        reason = "The prices came in groups (maybe different versions of the item). I used the biggest group of similar prices. Name the exact model to be sure."
    elif failures:
        reason = "Some searches did not finish: " + "; ".join(sorted(set(failures))) + "."
    result = ResearchResult(
        **base,
        outliers_removed=len(dropped),
        low=stats.low,
        median=stats.median,
        high=stats.high,
        n_sources=stats.n_sources,
        regions=stats.regions,
        confidence=confidence,
        available=True,
        reason=reason,
        sources=[Source(title=o.title, url=o.url, price=o.price, region=o.region, seller=o.seller) for o in kept],
    )
    if deps.cache is not None and not failures:
        await asyncio.to_thread(deps.cache.put, key, result.model_dump())
    return result


# ---------------------------------------------------------------- what the dashboard shows


def describe(result: ResearchResult) -> tuple[str, list[dict]]:
    """The text and source links for the agent's timeline (an `events` row)."""
    if not result.available:
        return f"Research unavailable. {result.reason}", []
    text = (
        f"Researcher found a fair price of {format_price(result.low, result.currency)} to "
        f"{format_price(result.high, result.currency)} from {result.n_sources} sources "
        f"({result.confidence} confidence)."
    )
    top = [{"title": s.title, "url": s.url} for s in result.sources[:5]]
    return text, top
