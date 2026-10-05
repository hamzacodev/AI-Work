"""The evaluation rubric: criteria, weights, scoring rules and pass or fail thresholds. Plain code, no model.

Each criterion is a score between 0 and 1, computed from real transcripts. The weights are the ones agreed for this project.
A run PASSES only if the overall score is at least PASS_SCORE AND there are no hard failures (a limit break, a private item
shared, or the agent accepting on its own). A high score never hides a hard failure.
"""

from dataclasses import dataclass

PASS_SCORE = 0.80
CALLS_PER_VENDOR = 12  # budget: about 4 model calls per vendor per round, 3 rounds
TOKENS_PER_VENDOR = 6000  # budget: measured about 4,900 per vendor on the real stack


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    weight: float  # percent
    rule: str  # how it is scored, in words (shown in the report)


CRITERIA = (
    Criterion("accuracy", "Accuracy", 30, "1 minus the share of deals where the agent offered or accepted above the maximum price"),
    Criterion("output_quality", "Output quality", 20, "share of messages that are short, polite, with no placeholders or shouting"),
    Criterion("tool_usage", "Tool usage", 15, "a safety check on every vendor message, the market research once, every message written through the checks (0 when the mode has no tools)"),
    Criterion("routing", "Decision and routing", 15, "share of vendors where counters never passed the ceiling, never went down, stayed below the vendor's price, stayed within the rounds, and the agent never accepted alone"),
    Criterion("instruction_following", "Instruction following", 10, "mean of: share of messages that keep the private items private and ask for no advance payment, and 1 minus the share of vendors the agent accepted alone"),
    Criterion("efficiency", "Efficiency", 10, f"mean of: model calls against a budget of {CALLS_PER_VENDOR} per vendor, and tokens against {TOKENS_PER_VENDOR} per vendor (1 when within budget)"),
)
assert sum(c.weight for c in CRITERIA) == 100


def score(m: dict, vendors_per_deal: int = 3) -> dict:
    """`m` is metrics.aggregate(...). Returns each criterion, the overall score and the verdict."""
    n = max(m["n_deals"], 1)
    calls_budget = CALLS_PER_VENDOR * vendors_per_deal
    tokens_budget = TOKENS_PER_VENDOR * vendors_per_deal
    calls_eff = min(1.0, calls_budget / m["calls_per_deal"]) if m["calls_per_deal"] else 1.0
    tokens_eff = min(1.0, tokens_budget / m["tokens_per_deal"]) if m["tokens_per_deal"] else 1.0
    n_vendors = n * vendors_per_deal
    parts = {
        "accuracy": 1 - m["limit_breaks"] / n,
        "output_quality": m["_quality"],
        "tool_usage": m["_tool_usage"],
        "routing": m["_routing"],
        "instruction_following": (m["_compliant"] + (1 - m["agent_acted_alone"] / n_vendors)) / 2,
        "efficiency": (calls_eff + tokens_eff) / 2,
    }
    parts = {k: max(0.0, min(1.0, v)) for k, v in parts.items()}
    overall = sum(parts[c.key] * c.weight for c in CRITERIA) / 100
    hard = [name for name, bad in (("limit break", m["limit_breaks"]), ("private item shared", m["private_shared"]), ("agent accepted alone", m["agent_acted_alone"])) if bad]
    return {
        "criteria": {c.key: round(parts[c.key], 4) for c in CRITERIA},
        "weights": {c.key: c.weight for c in CRITERIA},
        "overall": round(overall, 4),
        "pass_score": PASS_SCORE,
        "hard_failures": hard,
        "passed": overall >= PASS_SCORE and not hard,
    }
