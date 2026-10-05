import pytest

from app.agents.firm_price import FirmVerdict, read_firmness, scan
from app.core.llm import BudgetExhausted
from app.negotiation.strategy import next_firm_state


class FakeLLM:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    async def complete_json(self, role, system, user, schema, deal_id=None):
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.mark.parametrize(
    "text",
    [
        "Our price is $840 final. Fixed, no discount.",
        "$840 is the final price.",
        "Sorry, the price is fixed.",
        "I cannot go lower than that.",
        "I can't come down any more.",
        "That's my final offer.",
        "Non-negotiable.",
        "No further discount possible.",
        "Take it or leave it.",
        "No bargaining please.",
        "We won't go any lower.",
    ],
)
def test_clear_final_price_phrases_are_firm(text):
    assert scan(text) == "firm"


@pytest.mark.parametrize(
    "text",
    [
        "Our price is $880, ready to ship.",
        "Is your price final? Mine is $800.",  # a question is not firm (the "final" is not a vendor refusal)
        "Sure, let me think about it.",
        "$850 and delivery is free.",
        "We can look at a better price next week.",
    ],
)
def test_normal_messages_are_not_firm(text):
    assert scan(text) in ("none", "soft")
    assert scan(text) != "firm"


@pytest.mark.parametrize(
    "text",
    [
        "I can't go lower, but if you buy two I can do $800 each.",
        "The price is final unless you take three units.",
        "Fixed price, but for 3 units I could talk.",
    ],
)
def test_a_final_price_with_a_door_open_is_not_firm_by_rules(text):
    assert scan(text) == "soft"  # the model decides


async def test_clear_phrases_are_firm_without_calling_the_model():
    llm = FakeLLM(FirmVerdict(firm=False))
    r = await read_firmness("This is our final price.", llm)
    assert r.firm and r.decided_by == "rules" and llm.calls == 0


async def test_normal_messages_do_not_cost_a_model_call():
    llm = FakeLLM(FirmVerdict(firm=True))
    r = await read_firmness("Our best price is $880, delivery in 3 days.", llm)
    assert not r.firm and llm.calls == 0


async def test_soft_wording_goes_to_the_model():
    llm = FakeLLM(FirmVerdict(firm=True, reason="No room left."))
    r = await read_firmness("That is about the best I can do, there is very little margin.", llm)
    assert r.firm and r.decided_by == "model" and llm.calls == 1
    llm = FakeLLM(FirmVerdict(firm=False))
    assert not (await read_firmness("Not much room, but let me check with my boss.", llm)).firm


async def test_if_the_model_fails_the_agent_keeps_negotiating_within_its_limits():
    r = await read_firmness("There is very little margin left.", FakeLLM(BudgetExhausted()))
    assert not r.firm


# ---------------------------------------------------------------- the memory of "firm"


def test_firm_stays_firm_until_the_vendor_lowers_the_price():
    assert next_firm_state(False, True, 880, 840, 0) == (True, 0)
    assert next_firm_state(True, False, 840, 840, 1) == (True, 1)  # silent repeat: still firm, pushes kept
    assert next_firm_state(True, True, 840, 840, 1) == (True, 1)  # says it again: the push count is not reset
    assert next_firm_state(True, False, 840, 800, 2) == (False, 0)  # they moved: open again
    assert next_firm_state(False, False, 880, 840, 0) == (False, 0)
