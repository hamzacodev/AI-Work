"""Runs the Simulator with the REAL model (Ollama by default).

Run from backend/:  uv run python scripts/check_simulator.py
Part 1: price curves against a stand-in buyer (code only).
Part 2: how often the model's wording passes the code's check of the price.
Part 3: the Attacker's whole attack library through the real Safety Guard.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from app.agents.safety_guard import check_message
from app.agents.safety_rules import scan, strongest
from app.core.llm import get_llm
from app.guardrails.prices import extract_prices
from app.simulator.personas import ATTACKS, PERSONAS
from app.simulator.vendor_sim import VendorSim

MEDIAN = 700.0


async def part1() -> None:
    print("PART 1: price curves (market median 700, buyer starts at 560 and moves up 30% of the gap)\n")
    for name in PERSONAS:
        sim = VendorSim(name, MEDIAN, item="Dell XPS 15", seed=1)
        t = await sim.opening()
        line = [f"open {t.price:.0f}"]
        counter = 560.0
        for _ in range(5):
            t = await sim.reply(counter)
            line.append(f"{t.price:.0f}" + ("*" if t.agreed else ""))
            counter = round(counter + 0.3 * (t.price - counter))
        print(f"  {name:9} floor {sim.floor:.0f} | " + " -> ".join(line))
    print()


async def part2() -> None:
    llm = get_llm()
    print(f"PART 2: model wording ({llm.model_name('fast')}). The code keeps it only if it states exactly the right price.\n")
    kept = total = 0
    for name in PERSONAS:
        for seed in range(3):
            sim = VendorSim(name, MEDIAN, item="Dell XPS 15", seed=seed, llm=llm)
            plain = VendorSim(name, MEDIAN, item="Dell XPS 15", seed=seed)
            t = await sim.opening()
            template_turn = await plain.opening()
            # the model's sentence is used when the text differs from the template-only version's first sentence
            first = t.text.split(". ")[0]
            used_model = first not in template_turn.text
            prices = [p.value for p in extract_prices(t.text) if abs(p.value - t.price) < 0.01]
            assert prices, "the vendor's own price must always be in the text"
            kept += used_model
            total += 1
            if seed == 0:
                print(f"  {name:9} {'model' if used_model else 'template':8} | {t.text[:100]}")
    print(f"\n  model wording accepted by the code: {kept}/{total}\n")


async def part3() -> None:
    llm = get_llm()
    print("PART 3: the Attacker's whole attack library through the real Safety Guard\n")
    t0 = time.time()
    res = {"obvious": [0, 0], "sneaky": [0, 0]}
    exact = {"obvious": 0, "sneaky": 0}
    misses = []
    for kind, level, expected, text in ATTACKS:
        r = await check_message(text, llm)
        res[level][1] += 1
        if r.verdict != "ok":
            res[level][0] += 1
        if r.verdict == expected:
            exact[level] += 1
        else:
            misses.append((level, expected, r.verdict, text))
        rules = strongest(scan(text)[0])
        print(f"  {'blocked' if r.verdict != 'ok' else 'PASSED '} [{level:7}] expected={expected:17} got={r.verdict:17} rules={rules:17} | {text[:50]}")
    print()
    for level in ("obvious", "sneaky"):
        got, n = res[level]
        print(f"  {level:7}: flagged {got}/{n} ({100 * got / n:.0f}%), exact label {exact[level]}/{n}")
    total = sum(v[0] for v in res.values()) / sum(v[1] for v in res.values())
    print(f"  tricks blocked overall: {100 * total:.0f}%   ({time.time() - t0:.0f}s)")
    passed = [m for m in misses if m[2] == "ok"]
    print(f"  attacks that passed as ok: {len(passed)}")
    for _, _, _, text in passed:
        print(f"     - {text}")


async def main() -> int:
    await part1()
    await part2()
    await part3()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
