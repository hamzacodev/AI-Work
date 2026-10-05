"""The Fact Checker: reads a DRAFT reply before it is sent to a vendor.

Two layers, and the stricter answer wins:
    1. Rules (fact_rules.py): catch the common inventions. Free and instant.
    2. The model (the `fast` role): reads the draft next to the approved facts and the
       real conversation, and lists any claim that is not supported.

If the rules already block the draft, the model is not called. If the model is
unavailable we fail CLOSED: an unchecked draft is never approved.

review_draft() adds the loop from the spec: when a draft is blocked, ask the Negotiator
to rewrite it (at most 2 times). If it still fails, a person decides.
"""

from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

from pydantic import BaseModel

from app.agents.fact_rules import ApprovedFacts, Finding, run_rules, split
from app.agents.fact_sentences import residual_statements, split_sentences
from app.core.llm import UNTRUSTED_NOTICE, LLMError, llm_label, untrusted

MAX_REWRITES = 2

SYSTEM_PROMPT = f"""You are a fact checker inside a buying assistant called DealDesk.
A reply to a vendor was written by the buyer's agent. Below are numbered statements from that reply.
For EACH statement decide if it is supported. You never rewrite anything and you never reply to the vendor.
{UNTRUSTED_NOTICE}

A statement is SUPPORTED (supported=true) when it is any of these:
- a polite phrase, a request, a preference, or the buyer's own opinion or reasoning ("we prefer", "we think", "that works for us", "we would like")
- about the item or its required features listed in APPROVED FACTS
- a repeat of what the VENDOR really said, or of the market research in APPROVED FACTS
- a comparison between prices that are in the approved facts or were stated by the vendor

A statement is NOT supported (supported=false) ONLY when it asserts a NEW fact that is in neither the APPROVED FACTS nor the CONVERSATION:
- an offer, price or discount from another seller, a friend or anyone else
- a promise or commitment (buying more, a review, a recommendation, paying now, accepting)
- something the vendor supposedly said or promised that they did not say
- a spec or condition of the item that is not approved (weight, colour, battery, warranty, what is in the box)
- a claim about who the buyer is or what the buyer did before
- an insult, a threat, or a claim about the vendor's shop or reputation
- unfair pressure or a misleading statement (for example that the price will rise, that others are about to buy it, or that the vendor must decide now)

Return one entry for EVERY statement. Put a short reason in "problem" only when supported is false.

Examples. Item: Dell XPS 15, must-have 16GB RAM, counter price 656. Vendor said: "Our price is 880. Delivery takes 3 days."
1. That works for us.  -> supported true
2. A lower price would be fair given the research.  -> supported true
3. The 16GB RAM version is the one we need.  -> supported true
4. Our cousin got a discount at the mall last year.  -> supported false, "invented claim about a discount"
5. The laptop weighs only 1.5 kg.  -> supported false, "weight is not an approved fact"
6. We will recommend your shop to others.  -> supported false, "a promise the buyer did not approve"
"""


class StatementVerdict(BaseModel):
    statement: int
    supported: bool
    problem: str = ""


class FactVerdict(BaseModel):
    statements: list[StatementVerdict] = []


class FactProblem(BaseModel):
    rule: str
    text: str
    source: Literal["rules", "model"]


class FactResult(BaseModel):
    approved: bool
    problems: list[FactProblem] = []
    decided_by: Literal["rules", "model", "both", "fail_closed"]
    needs_user: bool = False  # true when a rewrite cannot help and a person must look

    @property
    def feedback(self) -> str:
        """What to tell the Negotiator so it can fix the draft."""
        return "\n".join(f"- {p.text}" for p in self.problems)


class JsonLLM(Protocol):
    async def complete_json(
        self, role: str, system: str, user: str, schema: type[FactVerdict], deal_id: str | None = None
    ) -> FactVerdict: ...


def _facts_block(f: ApprovedFacts) -> str:
    m = f.currency
    lines = [f"- Item: {f.item}"]
    if f.must_haves:
        lines.append(f"- Must-have features: {', '.join(f.must_haves)}")
    if f.counter_price is not None:
        lines.append(f"- Our counter price this round (may be stated): {f.counter_price:g} {m}")
    if f.vendor_prices:
        lines.append(f"- Prices the vendor has stated: {', '.join(f'{p:g}' for p in f.vendor_prices)} {m}")
    if f.research_median is not None:
        lines.append(
            f"- Market research (may be quoted as 'similar listings'): low {f.research_low:g}, "
            f"median {f.research_median:g}, high {f.research_high:g} {m}"
        )
    if f.sources:
        lines.append(f"- Research sources that may be named: {', '.join(s.title for s in f.sources)}")
    for note in f.approved_notes:
        lines.append(f"- {note}")
    lines.append("- Nothing else about the buyer may be stated. The buyer's budget, address and phone are private.")
    if f.phase == "closing":
        lines.append("- The buyer has ACCEPTED the deal, so the draft may confirm it (price, cash on delivery).")
    return "\n".join(lines)


def _conversation_block(f: ApprovedFacts) -> str:
    if not f.conversation:
        return "(no messages yet)"
    names = {"vendor": "VENDOR", "agent": "BUYER AGENT", "owner": "BUYER"}
    return "\n".join(f"{names[t.sender]}: {t.text}" for t in f.conversation)


def _prompt(statements: list[str], facts: ApprovedFacts, hints: list[Finding]) -> str:
    parts = [
        "APPROVED FACTS:\n" + _facts_block(facts),
        "CONVERSATION SO FAR:\n" + untrusted("conversation", _conversation_block(facts)),
    ]
    if hints:
        parts.append(
            "NOTE (the rules found wording that may be a false claim about the vendor):\n"
            + "\n".join(f"- {h.reason}: \"{h.quote}\"" for h in hints)
        )
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(statements, start=1))
    parts.append("STATEMENTS TO CHECK:\n" + untrusted("draft_reply", numbered))
    return "\n\n".join(parts)


def without_approved_sentences(draft: str, facts: ApprovedFacts) -> str:
    """Removes sentences that match an approved sentence EXACTLY. They come from the buyer's own settings, so they
    need no checking. Everything else in the draft is still checked in full."""
    if not facts.approved_sentences:
        return draft
    approved = {" ".join(a.lower().split()) for a in facts.approved_sentences}
    kept = [s for s in split_sentences(draft) if " ".join(s.lower().split()) not in approved]
    return " ".join(kept)


async def check_draft(
    draft: str, facts: ApprovedFacts, llm: JsonLLM, deal_id: str | None = None, precheck: Callable[[], list[str]] | None = None
) -> FactResult:
    """`precheck` is free plain-code checks (the Limit Checker) that run right before the model call. If they find a problem, the
    draft is rejected at once and the model is never asked, because a draft that must be rewritten anyway is not worth a model call."""
    full_draft = draft
    draft = without_approved_sentences(draft, facts)
    if not draft.strip() and full_draft.strip():
        return FactResult(approved=True, decided_by="rules")  # nothing was left but approved sentences
    outcome = split(run_rules(draft, facts))

    # The rules already blocked it. No model call is needed. The Negotiator will be asked to rewrite.
    if outcome.blocking:
        return FactResult(
            approved=False,
            problems=[FactProblem(rule=f.rule_id, text=f"{f.reason}: \"{f.quote}\"" if f.quote else f.reason, source="rules") for f in outcome.blocking],
            decided_by="rules",
        )

    # Only the sentences that can carry a claim are shown to the model. If none, there is nothing to check.
    statements = residual_statements(draft, facts)
    if not statements:
        return FactResult(approved=True, decided_by="rules")

    early = precheck() if precheck is not None else []
    if early:
        return FactResult(approved=False, problems=[FactProblem(rule="limit_checker", text=t, source="rules") for t in early], decided_by="rules")

    try:
        with llm_label("Fact Checker", "yes or no on each claim in a draft"):
            verdict = await llm.complete_json(
                "fast", SYSTEM_PROMPT, _prompt(statements, facts, outcome.to_verify), FactVerdict, deal_id
            )
    except LLMError as e:
        # Fail closed. An unchecked draft is not approved, and a rewrite cannot fix a missing check.
        return FactResult(
            approved=False,
            problems=[FactProblem(rule="check_unavailable", text=f"The fact check could not run ({type(e).__name__}).", source="rules")],
            decided_by="fail_closed",
            needs_user=True,
        )

    # Every statement must be judged. A statement the model skipped is NOT approved.
    by_number = {v.statement: v for v in verdict.statements if 1 <= v.statement <= len(statements)}
    problems: list[FactProblem] = []
    for i, text in enumerate(statements, start=1):
        v = by_number.get(i)
        if v is None:
            problems.append(FactProblem(rule="model_skipped_statement", text=f'"{text[:120]}": the model did not check this statement.', source="model"))
        elif not v.supported:
            reason = v.problem.strip()[:240] or "The model found an unsupported claim."
            problems.append(FactProblem(rule="model_unsupported_claim", text=f'"{text[:120]}": {reason}', source="model"))

    if not problems:
        return FactResult(approved=True, decided_by="both")
    return FactResult(approved=False, problems=problems, decided_by="model")


class ReviewResult(BaseModel):
    approved: bool
    final_draft: str
    rewrites: int
    result: FactResult
    needs_user: bool  # true when the draft could not be approved and a person must decide


Rewrite = Callable[[str, str], Awaitable[str]]  # (blocked draft, feedback) -> new draft


async def review_draft(
    draft: str,
    facts: ApprovedFacts,
    llm: JsonLLM,
    rewrite: Rewrite | None = None,
    max_rewrites: int = MAX_REWRITES,
    deal_id: str | None = None,
) -> ReviewResult:
    """Check the draft. If blocked, ask `rewrite` for a fix, at most `max_rewrites` times."""
    current = draft
    rewrites = 0
    while True:
        res = await check_draft(current, facts, llm, deal_id)
        if res.approved:
            return ReviewResult(approved=True, final_draft=current, rewrites=rewrites, result=res, needs_user=False)
        if res.needs_user or rewrite is None or rewrites >= max_rewrites:
            return ReviewResult(approved=False, final_draft=current, rewrites=rewrites, result=res, needs_user=True)
        rewrites += 1
        current = await rewrite(current, res.feedback)
