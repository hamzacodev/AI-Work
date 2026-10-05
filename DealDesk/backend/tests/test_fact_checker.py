import pytest

from app.agents.fact_checker import (
    FactVerdict,
    StatementVerdict,
    check_draft,
    review_draft,
)
from app.agents.fact_rules import ApprovedFacts, Turn
from app.core.llm import BudgetExhausted, LLMError, LLMInvalidOutput

FACTS = ApprovedFacts(
    item="Dell XPS 15",
    must_haves=["16GB RAM"],
    counter_price=656,
    vendor_prices=[880],
    research_low=640,
    research_median=700,
    research_high=790,
    conversation=[Turn(sender="vendor", text="Hi. Our price is $880.")],
)

GOOD = "Thank you for the quick reply. Could you do $656?"  # every sentence is safe, no model needed
NEEDS_MODEL = "The laptop is the 15 inch model. Could you do $656?"  # one statement the model must read
SNEAKY = "A friend across town told us the same laptop is selling for far less."


class FakeLLM:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[dict] = []

    async def complete_json(self, role, system, user, schema, deal_id=None):
        self.calls.append({"role": role, "system": system, "user": user})
        item = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(item, Exception):
            raise item
        return item


def verdict(n: int, bad: dict[int, str] | None = None) -> FactVerdict:
    """The model's answer for n statements. `bad` maps a statement number to the reason it is unsupported."""
    bad = bad or {}
    return FactVerdict(
        statements=[StatementVerdict(statement=i, supported=i not in bad, problem=bad.get(i, "")) for i in range(1, n + 1)]
    )


def no_problems(n: int = 1) -> FakeLLM:
    return FakeLLM(verdict(n))


def problem(n: int, text: str, total: int = 1) -> FakeLLM:
    return FakeLLM(verdict(total, {n: text}))


# ---------------------------------------------------------------- layers


async def test_draft_with_only_safe_sentences_is_approved_without_a_model_call():
    llm = no_problems()
    r = await check_draft(GOOD, FACTS, llm)
    assert r.approved and llm.calls == []


async def test_a_statement_is_checked_by_the_model_and_approved_when_clean():
    llm = no_problems()
    r = await check_draft(NEEDS_MODEL, FACTS, llm)
    assert r.approved and r.decided_by == "both" and len(llm.calls) == 1


async def test_rules_block_without_calling_the_model():
    llm = no_problems()
    r = await check_draft("Another shop offered me $650 and free delivery.", FACTS, llm)
    assert not r.approved and r.decided_by == "rules" and llm.calls == []
    assert any(p.rule == "competing_offer" for p in r.problems)


async def test_model_catches_what_the_rules_miss():
    r = await check_draft(SNEAKY, FACTS, problem(1, "Claims a friend found it cheaper, with no source."))
    assert not r.approved and r.decided_by == "model"
    assert r.problems[0].source == "model" and "friend across town" in r.problems[0].text


async def test_only_risky_statements_are_sent_to_the_model_and_numbered():
    llm = no_problems()
    await check_draft("Thanks. The screen is OLED. Could you do $656?", FACTS, llm)
    user = llm.calls[0]["user"]
    assert "1. The screen is OLED." in user
    assert "Could you do" not in user and "Thanks." not in user


async def test_a_statement_the_model_skipped_is_not_approved():
    # the model answers about statement 7, which does not exist. Statement 1 was never judged.
    llm = FakeLLM(FactVerdict(statements=[StatementVerdict(statement=7, supported=True)]))
    r = await check_draft(NEEDS_MODEL, FACTS, llm)
    assert not r.approved and r.problems[0].rule == "model_skipped_statement"


async def test_an_empty_answer_is_not_approval():
    r = await check_draft(NEEDS_MODEL, FACTS, FakeLLM(FactVerdict(statements=[])))
    assert not r.approved


async def test_an_unsupported_statement_with_no_reason_still_blocks():
    r = await check_draft(NEEDS_MODEL, FACTS, FakeLLM(verdict(1, {1: ""})))
    assert not r.approved and r.problems[0].text


async def test_every_statement_gets_its_own_verdict():
    draft = "The screen is OLED. We prefer a quick reply. The box is blue."
    llm = FakeLLM(verdict(3, {1: "Screen type is not approved."}))
    r = await check_draft(draft, FACTS, llm)
    assert not r.approved
    assert len([p for p in r.problems if p.source == "model"]) == 1
    assert "OLED" in r.problems[0].text


async def test_vendor_claim_hint_is_passed_to_the_model():
    llm = problem(1, "The vendor never said delivery is free.")
    draft = "You said delivery is free, so $656 is fair."
    r = await check_draft(draft, FACTS, llm)
    assert not r.approved
    assert "NOTE" in llm.calls[0]["user"]


async def test_model_prompt_has_facts_conversation_and_statements_in_data_tags():
    llm = no_problems()
    await check_draft(NEEDS_MODEL, FACTS, llm)
    call = llm.calls[0]
    assert call["role"] == "fast"
    assert "Dell XPS 15" in call["user"] and "656" in call["user"] and "880" in call["user"]
    assert "<conversation>" in call["user"] and "<draft_reply>" in call["user"]
    assert "The buyer's budget, address and phone are private" in call["user"]


async def test_the_buyers_maximum_price_can_never_be_in_the_prompt():
    llm = no_problems()
    await check_draft(NEEDS_MODEL, FACTS, llm)
    assert "maximum" not in llm.calls[0]["user"].lower()
    assert "max_price" not in ApprovedFacts.model_fields  # the facts object cannot even carry it


# ---------------------------------------------------------------- failing closed


@pytest.mark.parametrize("error", [LLMError("down"), LLMInvalidOutput("bad"), BudgetExhausted("limit")])
async def test_model_failure_never_approves_an_unchecked_statement(error):
    r = await check_draft(NEEDS_MODEL, FACTS, FakeLLM(error))
    assert not r.approved and r.decided_by == "fail_closed" and r.needs_user


async def test_model_failure_does_not_matter_when_nothing_needs_the_model():
    r = await check_draft(GOOD, FACTS, FakeLLM(LLMError("down")))
    assert r.approved


# ---------------------------------------------------------------- the rewrite loop


async def test_good_draft_needs_no_rewrite():
    async def rewrite(d, f):
        raise AssertionError("should not be called")

    r = await review_draft(GOOD, FACTS, no_problems(), rewrite)
    assert r.approved and r.rewrites == 0 and not r.needs_user


async def test_blocked_draft_is_rewritten_and_then_approved():
    seen: list[str] = []

    async def rewrite(draft, feedback):
        seen.append(feedback)
        return GOOD

    r = await review_draft("Another shop offered me less.", FACTS, no_problems(), rewrite)
    assert r.approved and r.rewrites == 1 and r.final_draft == GOOD
    assert "another seller" in seen[0].lower()  # the Negotiator is told what was wrong


async def test_rewrites_stop_after_two_and_the_user_decides():
    calls = 0

    async def rewrite(draft, feedback):
        nonlocal calls
        calls += 1
        return "Another shop offered me less."  # keeps lying

    r = await review_draft("Another shop offered me less.", FACTS, no_problems(), rewrite)
    assert not r.approved and r.needs_user and r.rewrites == 2 and calls == 2


async def test_no_rewrite_function_means_the_user_decides_at_once():
    r = await review_draft("We will buy in bulk.", FACTS, no_problems(), rewrite=None)
    assert not r.approved and r.needs_user and r.rewrites == 0


async def test_model_outage_skips_rewrites_because_a_rewrite_cannot_fix_it():
    async def rewrite(draft, feedback):
        raise AssertionError("rewrite cannot help when the check is down")

    r = await review_draft(NEEDS_MODEL, FACTS, FakeLLM(LLMError("down")), rewrite)
    assert not r.approved and r.needs_user and r.rewrites == 0


async def test_a_rewrite_that_passes_the_rules_is_still_checked_by_the_model():
    # draft 1 is blocked by the rules. Rewrite 1 passes the rules but the model objects.
    # Rewrite 2 is approved. Every draft is checked again, and the model was asked twice.
    llm = FakeLLM(verdict(1, {1: "Invented claim."}), verdict(1))
    drafts = iter([SNEAKY, NEEDS_MODEL])

    async def rewrite(draft, feedback):
        return next(drafts)

    r = await review_draft("Another shop offered me less.", FACTS, llm, rewrite)
    assert r.approved and r.rewrites == 2 and r.final_draft == NEEDS_MODEL
    assert len(llm.calls) == 2
