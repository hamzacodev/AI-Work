"""The scripted owner. It resolves the deals the agent hands back, so deals can close. It never accepts above the maximum."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    index: int  # which vendor of the deal
    offer: float
    advice: str | None  # the agent's recommendation: accept, counter, reject (None in the unprotected baseline)


def choose(candidates: list[Candidate], max_price: float, require_advice: bool = True) -> int | None:
    """The lowest offer that is at or below the maximum and that the agent advised accepting. None means reject everything.
    In the unprotected baseline there is no advice, so only the maximum counts."""
    ok = [c for c in candidates if c.offer <= max_price and (c.advice == "accept" or not require_advice)]
    return min(ok, key=lambda c: c.offer).index if ok else None
