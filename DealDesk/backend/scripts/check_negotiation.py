"""Shows the negotiation strategy playing against each fake vendor. No AI, no network, instant.

Run from backend/:  uv run python scripts/check_negotiation.py
You pay up to $800. The market is about $700 (low 630, high 770). Read each line as one round.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from app.core.money import format_price
from app.negotiation.strategy import Situation, decide, next_stall_count
from app.simulator.personas import PERSONAS
from app.simulator.vendor_sim import VendorSim

MAX_PRICE, MEDIAN = 800.0, 700.0
m = format_price


async def play(persona: str, seed: int = 1) -> None:
    p = PERSONAS[persona]
    sim = VendorSim(persona, MEDIAN, item="Dell XPS 15", seed=seed)
    turn = await sim.opening()
    print(f"\n=== {persona.upper()}  (opens {p.opening_markup:+.0%}, gives way {p.concession_rate:.0%} per round, lowest price {m(sim.floor)})")
    offers, last, rounds, stall, previous = [], None, 0, 0, None
    for n in range(1, 12):
        offers.append(turn.price)
        stall = next_stall_count(previous, turn.price, stall)
        previous = turn.price
        d = decide(Situation(
            max_price=MAX_PRICE, research_low=630, research_median=MEDIAN, research_high=770, research_confidence="medium",
            vendor_offer=turn.price, offers_so_far=tuple(offers), last_counter=last, rounds=rounds, stall_count=stall,
        ))  # fmt: skip
        print(f"  vendor asks {m(turn.price):>6}  ->  agent: {d.action.upper():9}", end="")
        if d.action == "counter":
            print(f" counter {m(d.counter_price)}")
            last, rounds = d.counter_price, rounds + 1
            turn = await sim.reply(d.counter_price)
            continue
        print(f" {d.reason[:92]}")
        if d.recommendation:
            print(f"        advice to you: {d.recommendation.action.upper()}. {d.recommendation.reason[:110]}")
        break


async def main() -> int:
    print(f"You pay up to {m(MAX_PRICE)}. The agent may never offer more than {m(760)} (95%). Target price: {m(665)}.")
    for name in PERSONAS:
        await play(name)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
