"""Turns the Researcher's result into advice for the maximum price. Plain code, no AI.

You type your maximum before the deal starts. This tells you what the item costs, so the maximum can be realistic:
- below the LOW price a deal is very unlikely,
- between the low and the typical (median) price a deal is possible,
- the agent opens about 7 percent below the market, so a maximum a little under the typical price leaves room to negotiate.
"""

from pydantic import BaseModel

from app.core.money import format_price
from app.schemas.research import ResearchResult, Source


class MarketAdvice(BaseModel):
    available: bool
    currency: str
    low: float | None = None
    median: float | None = None
    high: float | None = None
    confidence: str = "low"
    n_sources: int = 0
    from_cache: bool = False
    sources: list[Source] = []
    range_min: float | None = None  # a realistic maximum is from here ...
    range_max: float | None = None  # ... up to here
    text: str = ""  # the advice in plain words


def advise(r: ResearchResult) -> MarketAdvice:
    if not r.available or r.low is None or r.median is None or r.high is None:
        return MarketAdvice(
            available=False, currency=r.currency,
            text=f"I could not find a reliable market price. {r.reason} Enter the maximum you want to pay.".strip(),
        )  # fmt: skip
    m = lambda n: format_price(n, r.currency)
    lo, med = float(r.low), float(r.median)
    text = (
        f"Market price: {m(lo)} to {m(r.high)}, typical {m(med)} ({r.confidence} confidence, {r.n_sources} site{'s' if r.n_sources != 1 else ''}). "
        f"A realistic maximum is between {m(lo)} and {m(med)}. Below {m(lo)} a deal is very unlikely. "
        "The prices come from the web and can mix model years or versions, so check the sources."
    )
    if r.high > 1.5 * r.low:  # a very wide range usually means different versions of the product were mixed
        text += " Warning: the range is very wide, so these sources may be different versions of the product. Open them before you trust the numbers."
    return MarketAdvice(
        available=True, currency=r.currency, low=lo, median=med, high=float(r.high), confidence=r.confidence, n_sources=r.n_sources,
        from_cache=r.from_cache, sources=r.sources[:5], range_min=lo, range_max=med, text=text,
    )  # fmt: skip


def warning_for(max_price: float, advice: MarketAdvice) -> str | None:
    """A short warning when the maximum is far from the market, or None."""
    if not advice.available or advice.low is None:
        return None
    m = lambda n: format_price(n, advice.currency)
    if max_price < advice.low:
        return f"Your maximum of {m(max_price)} is below the lowest market price of {m(advice.low)}, so a deal is very unlikely."
    return None
