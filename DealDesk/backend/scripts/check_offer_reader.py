"""Reads vendor messages with the real model. Run: uv run python scripts/check_offer_reader.py"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from app.agents.offer_reader import read_offer
from app.core.llm import get_llm

CASES = [
    ("Our best price is $880, ready to ship.", 880),
    ("It was $950 last week, now $880 with free delivery.", 880),
    ("Others sell at $700 but ours is genuine, $790 final.", 790),
    ("Delivery is $15 within the city.", None),
    ("Price $900. Warranty extension is $60 extra.", 900),
    ("Retail is $1,000, my price is $820, delivery $30.", 820),
]


async def main() -> None:
    llm = get_llm()
    ok = 0
    for text, want in CASES:
        t = time.monotonic()
        r = await read_offer(text, llm, reference_price=700)
        good = r.price == want
        ok += good
        print(f"{'OK ' if good else 'BAD'} want={want} got={r.price} ({r.status}, {r.decided_by}, {time.monotonic() - t:.0f}s) {text}")
    print(f"{ok}/{len(CASES)} correct")


asyncio.run(main())
