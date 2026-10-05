"""Draws the progress bars in PROGRESS.md from progress.json.

Run from the project root:   python3 scripts/progress.py
Check only (no writing):     python3 scripts/progress.py --check
Needs only Python 3, nothing to install.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "progress.json"
TARGET = ROOT / "PROGRESS.md"
START, END = "<!-- PROGRESS-BAR:START -->", "<!-- PROGRESS-BAR:END -->"
WIDTH = 24


def bar(percent: float) -> str:
    filled = round(WIDTH * percent / 100)
    return "[" + "█" * filled + "░" * (WIDTH - filled) + "]"


def share(tasks: list[dict]) -> float:
    total = sum(t["weight"] for t in tasks)
    return 100 * sum(t["weight"] * t["done"] for t in tasks) / total if total else 0.0


def validate(data: dict) -> list[str]:
    problems = []
    total = sum(t["weight"] for t in data["tasks"])
    if abs(total - 100) > 0.001:
        problems.append(f"The task weights add up to {total}, not 100.")
    ids = {p["id"] for p in data["phases"]}
    for t in data["tasks"]:
        if t["phase"] not in ids:
            problems.append(f"Unknown phase in task: {t['title']}")
        if not 0 <= t["done"] <= 1:
            problems.append(f"'done' must be between 0 and 1: {t['title']}")
    return problems


def status(percent: float) -> str:
    return "done" if percent >= 99.995 else "not started" if percent <= 0 else "in progress"


def mark(percent: float, flag: str | None = None) -> str:
    """A green tick when finished, a yellow dot while in progress, an orange dot when not started.
    Unfinished work can also carry a flag after the status: a red dot for a blocker, a purple dot when it needs the user."""
    base = "✅ Done" if percent >= 99.995 else "🟠 Not started" if percent <= 0 else "🟡 In progress"
    if percent < 99.995 and flag == "blocked":
        return base + " · 🔴 Blocked"
    if percent < 99.995 and flag == "you":
        return base + " · 🟣 Needs you"
    return base


def flag_of(items: list[dict]) -> str | None:
    """The strongest flag among unfinished items: blocked beats waiting on you."""
    flags = {i.get("flag") or i.get("kind") for i in items if i.get("done", 0) < 0.99995}
    return "blocked" if "blocked" in flags else "you" if "you" in flags else None


def render(data: dict) -> str:
    tasks = data["tasks"]
    overall = share(tasks)
    left = 100 - overall
    lines = [START, "", "## Progress", "", "```text", f"PROJECT  {bar(overall)} {overall:5.1f}%   ({left:.1f}% left)", "```", ""]

    lines += ["**By phase** (each phase counts by its size)", "", "```text"]
    for p in data["phases"]:
        pt = [t for t in tasks if t["phase"] == p["id"]]
        pc = share(pt)
        weight = sum(t["weight"] for t in pt)
        lines.append(f"Phase {p['id']:<3}{p['name']:<32} {bar(pc)} {pc:5.1f}%   (worth {weight:g}%)")
    lines += ["```", "", "**By module** (each part of the system, across all phases)", "", "```text"]
    modules = list(dict.fromkeys(t["module"] for t in tasks))
    for m in modules:
        mt = [t for t in tasks if t["module"] == m]
        mc = share(mt)
        lines.append(f"{m:<28} {bar(mc)} {mc:5.1f}%")
    lines += ["```", "", "**Phase table**", "", "| Phase | What | Status | Done | Worth |", "|---|---|---|---|---|"]
    for p in data["phases"]:
        pt = [t for t in tasks if t["phase"] == p["id"]]
        pc = share(pt)
        extra = [{"kind": a["kind"]} for a in data.get("attention", []) if a.get("phase") == p["id"]]
        lines.append(f"| {p['id']} | {p['name']} | {mark(pc, flag_of(pt + extra))} | {pc:.0f}% | {sum(t['weight'] for t in pt):g}% |")
    lines += ["", "**Module table**", "", "| Module | Status | Done |", "|---|---|---|"]
    for m in modules:
        mt = [t for t in tasks if t["module"] == m]
        mc = share(mt)
        lines.append(f"| {m} | {mark(mc, flag_of(mt))} | {mc:.0f}% |")
    lines += ["", "**Every task**", "", "| Phase | Module | Task | Status | Size | Done |", "|---|---|---|---|---|---|"]
    for t in tasks:
        d = t["done"] * 100
        lines.append(f"| {t['phase']} | {t['module']} | {t['title']} | {mark(d, t.get('flag'))} | {t['weight']:g}% | {d:.0f}% |")
    waiting = [(t["phase"], t["title"], t.get("note", ""), t["flag"]) for t in tasks if t.get("flag") and t["done"] < 0.99995]
    waiting += [(a.get("phase", ""), a["title"], a.get("note", ""), a["kind"]) for a in data.get("attention", [])]
    lines += ["", "**Blockers and things that wait on you**", ""]
    if waiting:
        lines += ["| Flag | Phase | What | Note |", "|---|---|---|---|"]
        for phase, title, note, kind in sorted(waiting, key=lambda w: (w[3] != "blocked", w[0])):
            lines.append(f"| {'🔴 Blocked' if kind == 'blocked' else '🟣 Needs you'} | {phase} | {title} | {note} |")
    else:
        lines.append("Nothing is blocked and nothing waits on you right now.")
    lines += ["", "Key: ✅ done, 🟡 in progress, 🟠 not started, 🔴 blocked, 🟣 needs you (shown after the status).", "", "_Drawn by `python3 scripts/progress.py` from `progress.json`. Edit that file, then run the script. Sizes are estimates._", "", END]
    return "\n".join(lines)


def main() -> int:
    data = json.loads(DATA.read_text())
    problems = validate(data)
    if problems:
        print("\n".join(problems))
        return 1
    block = render(data)
    if "--check" in sys.argv:
        print(block)
        return 0
    text = TARGET.read_text()
    if START in text and END in text:
        before, rest = text.split(START, 1)
        _, after = rest.split(END, 1)
        text = before + block + after
    else:  # first time: put the block right under the first heading
        head, _, tail = text.partition("\n")
        text = head + "\n\n" + block + "\n" + tail
    TARGET.write_text(text)
    print(f"PROGRESS.md updated. Project: {share(data['tasks']):.1f}% done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
