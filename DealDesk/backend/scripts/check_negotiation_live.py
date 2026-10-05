"""A whole negotiation with the REAL model writing every message, against a fake vendor. Slow on a laptop CPU.

Run from backend/:  uv run python scripts/check_negotiation_live.py [persona]   (default: pushy)
You pay up to $800, the market is about $700. Code picks every price and every tactic sentence.
The model only writes the words, and every message passes the number check, the Fact Checker and the Limit Checker.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from app.agents.fact_rules import Source, Turn
from app.agents.negotiator import NegotiationContext, negotiate
from app.core.llm import get_llm
from app.core.money import format_price
from app.negotiation.strategy import Situation, decide, next_stall_count
from app.negotiation.tactics import Tactics
from app.simulator.vendor_sim import VendorSim

VENDOR = "sales@techhub.example.com"
MAX_PRICE, MEDIAN = 800.0, 700.0
TACTICS = Tactics(may_buy_quantity=2, may_buy_again=True, may_refer=True, can_decide_today=True)
SOURCES = [Source(title="Retailer A", url="https://a.example.com"), Source(title="Price tracker", url="https://t.example.com")]


async def main() -> int:
    persona = sys.argv[1] if len(sys.argv) > 1 else "pushy"
    llm = get_llm()
    sim = VendorSim(persona, MEDIAN, item="Dell XPS 15", seed=1)
    turn = await sim.opening()
    conversation = [Turn(sender="agent", text="Hello, I am interested in the Dell XPS 15 with 16GB RAM. What is your best price?"), Turn(sender="vendor", text=turn.text)]
    print(f"Persona: {persona}. You pay up to {format_price(MAX_PRICE)}, the market is about {format_price(MEDIAN)}.\n")
    offers: list[float] = []
    last = None
    rounds = stall = 0
    previous = None
    for _ in range(6):
        offers.append(turn.price)
        stall = next_stall_count(previous, turn.price, stall)
        previous = turn.price
        situation = Situation(
            max_price=MAX_PRICE, research_low=640, research_median=MEDIAN, research_high=790, research_confidence="medium",
            vendor_offer=turn.price, offers_so_far=tuple(offers), last_counter=last, rounds=rounds, stall_count=stall,
        )  # fmt: skip
        d = decide(situation)
        print(f"VENDOR  ({format_price(turn.price)}): {turn.text}")
        if d.action != "counter":
            print(f"\nAGENT STOPS and asks you: {d.reason}")
            if d.recommendation:
                print(f"  advice: {d.recommendation.action.upper()}. {d.recommendation.reason}")
            return 0
        c = NegotiationContext(
            decision=d, item="Dell XPS 15", must_haves=["16GB RAM"], currency="USD", max_price=MAX_PRICE, recipient=VENDOR,
            vendor_contacts=frozenset({VENDOR}), conversation=conversation, vendor_offer=turn.price, vendor_prices=tuple(offers),
            previous_counter=last, rounds=rounds, research_low=640, research_median=MEDIAN, research_high=790, sources=SOURCES,
            tactics=TACTICS, address="12 Example Street, Karachi", phone="+92 300 1234567",
        )  # fmt: skip
        t0 = time.time()
        r = await negotiate(c, llm)
        if not r.ok:
            print(f"\nAGENT could not write a safe message ({time.time() - t0:.0f}s) and asks you:")
            for p in r.problems:
                print("   -", p[:140])
            return 0
        print(f"AGENT   (counter {format_price(d.counter_price)}, round {rounds + 1}, {r.rewrites} rewrite(s), {time.time() - t0:.0f}s): {r.message}\n")
        sys.stdout.flush()
        conversation.append(Turn(sender="agent", text=r.message))
        last, rounds = d.counter_price, rounds + 1
        turn = await sim.reply(d.counter_price)
        conversation.append(Turn(sender="vendor", text=turn.text))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
