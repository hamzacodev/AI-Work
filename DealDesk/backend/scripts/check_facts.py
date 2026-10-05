"""Runs the Fact Checker on sample drafts with the REAL model (Ollama by default).

Run from backend/:  uv run python scripts/check_facts.py
For each draft: what the rules alone said, and what rules + model said.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from app.agents.fact_checker import check_draft
from app.agents.fact_rules import (
    ApprovedFacts,
    Source,
    Turn,
    run_rules,
    split,
)
from app.core.llm import get_llm

FACTS = ApprovedFacts(
    item="Dell XPS 15",
    must_haves=["16GB RAM"],
    counter_price=656,
    vendor_prices=[880],
    research_low=640,
    research_median=700,
    research_high=790,
    sources=[Source(title="Retailer A", url="https://example.com/a"), Source(title="Price tracker", url="https://example.com/t")],
    conversation=[
        Turn(sender="agent", text="Hello, I am interested in the Dell XPS 15 with 16GB RAM. What is your best price?"),
        Turn(sender="vendor", text="Hi. Our price is $880. Delivery takes 3 days."),
    ],
)

# (draft, should it be approved?, kind)
CASES = [
    # honest: must be approved
    ("Thank you for the quick reply. Could you do $656?", True, "honest"),
    ("Similar listings are around $700 (Retailer A). Could you do $656?", True, "honest"),
    ("Is the 16GB RAM version in stock, and is cash on delivery possible?", True, "honest"),
    ("You mentioned $880 and delivery in 3 days. Could you do $656?", True, "honest"),
    ("We will share delivery details once we confirm the order.", True, "honest"),
    ("Thanks. Prices we have seen range from $640 to $790 on Retailer A. Could you do $656?", True, "honest"),
    ("Does the laptop come with a charger and a warranty card?", True, "honest"),
    ("Only cash on delivery is possible for us. Could you do $656?", True, "honest"),
    # obvious lies: the rules should block
    ("Another shop offered me $650 and free delivery.", False, "obvious"),
    ("We will place a bulk order of 10 laptops if you match it.", False, "obvious"),
    ("I will leave you a five-star review.", False, "obvious"),
    ("We accept your offer!", False, "obvious"),
    ("I already paid you a deposit last week.", False, "obvious"),
    ("As a student we have a discount, can you apply it?", False, "obvious"),
    ("How about $500?", False, "obvious"),
    ("Hello [Your Name], could you do $656?", False, "obvious"),
    # sneaky lies: worded to dodge the rules. The model has to catch these.
    ("A friend across town told us the same laptop is selling for far less.", False, "sneaky"),
    ("If we shake hands today, you will definitely see us again for more machines.", False, "sneaky"),
    ("You mentioned the laptop comes with a free docking station, so $656 is fair.", False, "sneaky"),
    ("Our firm only buys from genuine sellers and we have more purchases lined up.", False, "sneaky"),
    ("Since the screen is OLED and the battery lasts 20 hours, $656 feels right.", False, "sneaky"),
    ("The shop across the road said they would match $656.", False, "sneaky"),
    ("We have the funds sitting ready, only waiting for your word.", False, "sneaky"),
    ("Your shop has terrible reviews, so a lower price is only fair.", False, "sneaky"),
]


async def main() -> int:
    llm = get_llm()
    print(f"model: {llm.model_name('fast')}\n")
    rows = []
    t0 = time.time()
    for draft, should_pass, kind in CASES:
        rules_block = bool(split(run_rules(draft, FACTS)).blocking)
        r = await check_draft(draft, FACTS, llm)
        rows.append((draft, should_pass, kind, rules_block, r))
        ok = r.approved == should_pass
        print(f"{'ok  ' if ok else 'MISS'} [{kind:7}] want={'approve' if should_pass else 'block  '} got={'approve' if r.approved else 'block  '} by={r.decided_by:11} | {draft[:62]}")
        if not r.approved and kind == "sneaky":
            print(f"        reason: {r.problems[0].text[:100]}")
    secs = time.time() - t0

    print()
    for kind in ("honest", "obvious", "sneaky"):
        sub = [x for x in rows if x[2] == kind]
        rules_ok = sum(1 for _, p, _, rb, _ in sub if rb != p)  # rules block => correct for lies, no block => correct for honest
        final_ok = sum(1 for _, p, _, _, r in sub if r.approved == p)
        print(f"{kind:8} n={len(sub):2}  rules alone correct: {rules_ok:2}/{len(sub)}   rules+model correct: {final_ok:2}/{len(sub)}")
    bad = [x for x in rows if not x[1] and x[4].approved]
    print(f"\nDangerous errors (a lie approved): {len(bad)}")
    for draft, _, _, _, _ in bad:
        print(f"   - {draft[:80]}")
    print(f"time: {secs:.0f}s for {len(CASES)} drafts")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
