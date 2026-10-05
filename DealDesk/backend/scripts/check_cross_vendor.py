"""Three scripted vendors, the real strategy and the real Best Offer Tracker. No model, no network.

Run from backend/:  uv run python scripts/check_cross_vendor.py
You will pay up to 800. The market is 640 to 790 around 700. Alpha says "final price", Beta and Gamma come down.
It shows, after every vendor message, what the agent decides: counter, leverage (tell the best offer we hold, no name),
hold (stop texting, wait for the others) or ask you. At the end it prints the deal summary.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from app.negotiation.strategy import (
    Situation,
    decide,
    next_firm_state,
    next_stall_count,
)
from app.negotiation.tracker import (
    VendorState,
    leverage_for,
    others_active,
    reengage_candidates,
    summarize,
)

MEDIAN, MAX = 700.0, 800.0
MAX_ROUNDS = 5  # the real default is 3. With 3 rounds most vendors run out before a better price appears.
SCRIPT = {  # (price, says "final price")
    "Alpha": [(880, False), (840, True), (840, True), (840, True), (840, True)],
    "Beta": [(780, False), (720, False), (680, False), (650, False), (650, False)],
    "Gamma": [(910, False), (870, False), (700, False), (640, False), (620, False)],
}


@dataclass
class V:
    name: str
    offer: float | None = None
    last_counter: float | None = None
    rounds: int = 0
    stall: int = 0
    firm: bool = False
    pushes: int = 0
    last_lever: float | None = None
    status: str = "negotiating"
    reason: str | None = None


vendors = [V(n) for n in SCRIPT]


def states() -> list[VendorState]:
    return [VendorState(v.name, v.name, v.offer, v.status, v.reason, v.firm, v.rounds, v.last_lever) for v in vendors]  # type: ignore[arg-type]


def act(v: V, tag: str) -> None:
    """Runs the strategy for one vendor with its current price and applies the decision."""
    st = states()
    lever = leverage_for(v.name, st, MEDIAN, MAX * 0.95)
    d = decide(Situation(
        max_price=MAX, research_low=640, research_median=MEDIAN, research_high=790, research_confidence="medium",
        max_rounds=MAX_ROUNDS, vendor_offer=v.offer, last_counter=v.last_counter, rounds=v.rounds, stall_count=v.stall,
        best_other_offer=lever, last_leverage=v.last_lever, others_active=others_active(v.name, st),
        firm=v.firm, firm_pushes=v.pushes,
    ))  # fmt: skip
    firm = " [says FINAL]" if v.firm else ""
    print(f"{v.name:6} {tag} ${v.offer:g}{firm} -> {d.action.upper():9} counter={d.counter_price} tells_best={d.leverage_price} {d.stop_reason or ''}")
    if d.action in ("counter", "leverage"):
        v.status, v.reason = "negotiating", None
        v.rounds += 1
        v.pushes += 1 if v.firm else 0
        if d.counter_price is not None:
            v.last_counter = d.counter_price
        if d.leverage_price is not None:
            v.last_lever = d.leverage_price
    else:
        v.status, v.reason = "paused", d.stop_reason


for sweep in range(5):
    print(f"\n=== Sweep {sweep + 1} ===")
    for v in vendors:
        price, says_firm = SCRIPT[v.name][sweep]
        if v.status == "paused":
            print(f"{v.name:6} (paused, we do not text) vendor still says ${price:g}")
            v.offer = price
            continue
        v.stall = next_stall_count(v.offer, price, v.stall)
        v.firm, v.pushes = next_firm_state(v.firm, says_firm, v.offer, price, v.pushes)
        v.offer = price
        act(v, "says")
    # A better price may have appeared since a vendor was paused. Wake those vendors up (the chat was never closed).
    for name in reengage_candidates(states(), MEDIAN, MAX * 0.95, MAX_ROUNDS):
        act(next(v for v in vendors if v.name == name), "wake-up, now")

print("\n" + summarize(states(), MEDIAN).headline)
for r in summarize(states(), MEDIAN).ranking:
    print(f"  {r.name:6} ${r.price:g}  firm={r.firm}  {r.status} {r.stop_reason or ''}")
