"""Runs the Negotiator with the REAL model (Ollama by default). Slow on a laptop CPU.

Run from backend/:  uv run python scripts/check_negotiator.py
You will pay up to $800. The market is $640 to $790 around $700. The vendor says $800.
It shows every message the model wrote, why a draft was rejected, and what was finally approved.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from app.agents.fact_rules import Source, Turn
from app.agents.negotiator import NegotiationContext, negotiate
from app.core.llm import get_llm
from app.negotiation.strategy import Decision, Situation, decide
from app.negotiation.tactics import Tactics

VENDOR = "sales@techhub.example.com"


def make(action_situation: Situation, tactics: Tactics, conversation: list[Turn]) -> NegotiationContext:
    d: Decision = decide(action_situation)
    s = action_situation
    return NegotiationContext(
        decision=d, item="Dell XPS 15", must_haves=["16GB RAM"], currency="USD", max_price=s.max_price,
        recipient=VENDOR, vendor_contacts=frozenset({VENDOR}), conversation=conversation, vendor_offer=s.vendor_offer,
        vendor_prices=s.offers_so_far, previous_counter=s.last_counter, rounds=s.rounds,
        research_low=s.research_low, research_median=s.research_median, research_high=s.research_high,
        sources=[Source(title="Retailer A", url="https://a.example.com"), Source(title="Price tracker", url="https://t.example.com")],
        tactics=tactics, address="12 Example Street, Karachi", phone="+92 300 1234567",
    )  # fmt: skip


BASE = {"max_price": 800.0, "research_low": 640.0, "research_median": 700.0, "research_high": 790.0, "research_confidence": "medium"}
SCENARIOS = [
    ("1. First message (no price yet)", Situation(**BASE), Tactics(), []),
    ("2. Counter, nothing approved", Situation(**BASE, vendor_offer=800.0, offers_so_far=(800.0,)), Tactics(),
     [Turn(sender="agent", text="Hello, I am interested in the Dell XPS 15 with 16GB RAM. What is your best price?"), Turn(sender="vendor", text="Hi. Our price is $800.")]),
    ("3. Counter, you approved: buy 2, buy again, a friend may buy", Situation(**BASE, vendor_offer=800.0, offers_so_far=(800.0,)),
     Tactics(may_buy_quantity=2, may_buy_again=True, may_refer=True),
     [Turn(sender="agent", text="Hello, I am interested in the Dell XPS 15 with 16GB RAM. What is your best price?"), Turn(sender="vendor", text="Hi. Our price is $800.")]),
]  # fmt: skip


async def main() -> int:
    llm = get_llm()
    only = int(sys.argv[1]) if len(sys.argv) > 1 else None  # run one scenario: python scripts/check_negotiator.py 2
    for n, (title, situation, tactics, conversation) in enumerate(SCENARIOS):
        if only is not None and n != only:
            continue
        c = make(situation, tactics, conversation)
        t0 = time.time()
        r = await negotiate(c, llm)
        print("=" * 100)
        print(title, f"   (code chose: {c.decision.action}" + (f" ${c.decision.counter_price:.0f}" if c.decision.counter_price else "") + f", {time.time() - t0:.0f}s)")
        if r.ok:
            print(f"  APPROVED after {r.rewrites} rewrite(s):\n    {r.message}")
        else:
            print("  NOT SENT, the user is asked. Reasons:")
            for p in r.problems:
                print("    -", p[:140])
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
