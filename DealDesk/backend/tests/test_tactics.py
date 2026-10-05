import pytest

from app.agents.fact_checker import _facts_block
from app.agents.fact_rules import ApprovedFacts, run_rules, split
from app.negotiation.tactics import Tactics


def facts(**over) -> ApprovedFacts:
    t = Tactics(**{k: v for k, v in over.items() if k in Tactics.model_fields})
    base = {"item": "Dell XPS 15", "counter_price": 651, "vendor_prices": [800]}
    base.update({k: v for k, v in over.items() if k not in Tactics.model_fields})
    return ApprovedFacts(
        may_buy_quantity=t.may_buy_quantity, may_buy_again=t.may_buy_again, may_refer=t.may_refer,
        approved_notes=t.approved_notes(), **base,
    )  # fmt: skip


def blocked(draft: str, f: ApprovedFacts) -> set[str]:
    return {x.rule_id for x in split(run_rules(draft, f)).blocking}


# ---------------------------------------------------------------- by default these are all blocked

DEFAULT_BLOCKED = [
    "If you give us a good price, we would place a bulk order of ten.",
    "If the price is good we will buy two.",
    "We will buy two units from you.",
    "If this goes well, we will buy from you again.",
    "If the price is good, I will tell my friends about you.",
]


@pytest.mark.parametrize("draft", DEFAULT_BLOCKED)
def test_without_approval_the_promises_are_blocked(draft):
    assert blocked(draft, facts()) != set(), draft


# ---------------------------------------------------------------- with approval, as conditions only


def test_buying_two_is_allowed_when_the_buyer_approved_it_and_it_is_a_condition():
    f = facts(may_buy_quantity=2)
    assert blocked("If the price is good, we would buy two.", f) == set()
    assert blocked("If you can do $651 we will buy two units.", f) == set()
    assert blocked("We would be happy to buy 2 if we agree a good price.", f) == set()


def test_a_firm_unconditional_promise_is_never_allowed():
    f = facts(may_buy_quantity=2, may_buy_again=True, may_refer=True)
    assert blocked("We will buy two.", f) != set()
    assert blocked("We will buy from you again.", f) != set()
    assert blocked("We will tell my friends about you.", f) != set()


def test_more_than_the_approved_quantity_is_blocked():
    f = facts(may_buy_quantity=2)
    assert blocked("If the price is good, we would buy five.", f) != set()
    assert blocked("If the price is good, we would buy 10 units.", f) != set()
    assert blocked("If the price is good, we would buy two.", f) == set()


def test_buying_again_is_allowed_only_when_approved():
    assert blocked("If this goes well, we will buy from you again.", facts()) != set()
    assert blocked("If this goes well, we will buy from you again.", facts(may_buy_again=True)) == set()


def test_buying_two_does_not_approve_buying_again():
    assert blocked("If this goes well, we will buy from you again.", facts(may_buy_quantity=2)) != set()


def test_telling_friends_is_allowed_only_when_approved_and_conditional():
    draft = "If the price is good, I will tell my friends about you."
    assert blocked(draft, facts()) != set()
    assert blocked(draft, facts(may_refer=True)) == set()


# ---------------------------------------------------------------- approvals never open other doors


@pytest.mark.parametrize(
    "draft",
    [
        "If the price is good we will leave a five-star review.",
        "Another shop offered me $600, so if you match it we will buy two.",
        "If you agree we will pay in advance.",
        "I will report you if you refuse, and buy two otherwise.",
        "We accept your offer, and if it goes well we will buy again.",
        "If the price is good, we are ready to buy right now.",
        "If you do $500 we will buy two.",  # an unapproved price is still blocked
    ],
)
def test_other_rules_still_block_even_with_every_tactic_approved(draft):
    f = facts(may_buy_quantity=2, may_buy_again=True, may_refer=True)
    assert blocked(draft, f) != set(), draft


# ---------------------------------------------------------------- what the model is told

ALL_ON = {"may_buy_quantity": 2, "may_buy_again": True, "may_refer": True, "can_decide_today": True, "keep_looking": True}


def test_defaults_allow_the_requests_but_none_of_the_claims():
    t = Tactics()
    assert t.good_rate_line and t.may_buy_quantity == 1 and not t.may_buy_again and not t.may_refer
    assert not t.can_decide_today and not t.keep_looking
    assert set(t.moves()) == {"extras", "best_price", "meet_halfway"}  # questions and process lines only, no promises


def test_every_approval_adds_a_move_a_note_for_the_fact_checker_and_a_line_for_the_negotiator():
    t = Tactics(**ALL_ON)
    assert set(t.moves()) == {"quantity", "refer", "again", "decide_today", "extras", "best_price", "meet_halfway", "keep_looking"}
    assert len(t.persuasion_lines()) == 11 and len(t.approved_notes()) == 9 and len(t.prompt_lines()) == 11  # 3 rapport lines and 8 moves
    notes = " ".join(t.approved_notes())
    assert "up to 2 units" in notes and "never name them" in notes and "other listings" in notes


def test_nothing_is_approved_when_everything_is_switched_off():
    t = Tactics(good_rate_line=False, ask_best_price=False, ask_extras=False, meet_halfway=False)
    assert t.approved_notes() == [] and t.prompt_lines() == [] and t.persuasion_lines() == []


def test_the_fact_checkers_list_of_approved_facts_includes_the_notes():
    block = _facts_block(facts(may_buy_quantity=2, may_refer=True))
    assert "up to 2 units" in block and "friend or family member" in block
    assert "Nothing else about the buyer may be stated" in block


def test_the_approved_quantity_has_sensible_limits():
    with pytest.raises(ValueError):
        Tactics(may_buy_quantity=0)
    with pytest.raises(ValueError):
        Tactics(may_buy_quantity=500)


# ---------------------------------------------------------------- the playbook: a different move in each round


def test_the_playbook_gives_a_different_move_each_round():
    t = Tactics(**ALL_ON)
    assert t.line_for_round(0) == "If we agree a good price, I would buy two."
    assert t.line_for_round(1) == "If the price is good, a friend of mine may also want one."
    assert t.line_for_round(2) == "I can move a little if you can come down a bit too."


def test_a_move_the_buyer_did_not_approve_is_skipped_for_the_next_one():
    t = Tactics(may_buy_again=True, can_decide_today=True)  # no quantity, no friend
    assert t.line_for_round(0) == "If this goes well, I would be happy to buy from you again."
    assert t.line_for_round(1) == "If this goes well, I would be happy to buy from you again."  # 'refer' skipped, 'again' next
    assert Tactics(can_decide_today=True).line_for_round(0) == "If we can agree on a price, I can decide today."


def test_with_only_the_default_requests_the_first_round_has_no_required_move():
    t = Tactics()
    assert t.line_for_round(0) is None  # opening hooks are claims, and none were approved
    assert t.line_for_round(1) == "Could you also include free delivery or the charger at that price?"
    assert t.line_for_round(2) == "I can move a little if you can come down a bit too."


def test_after_the_playbook_the_moves_take_turns():
    t = Tactics(**ALL_ON)
    seen = {t.line_for_round(i) for i in range(3, 3 + 8)}
    assert len(seen) == 8  # every allowed move comes round once


def test_nothing_required_when_nothing_is_allowed():
    off = Tactics(good_rate_line=False, ask_best_price=False, ask_extras=False, meet_halfway=False)
    assert [off.line_for_round(i) for i in range(6)] == [None] * 6


def test_the_keep_looking_move_is_off_unless_approved():
    assert "keep_looking" not in Tactics().moves()
    assert Tactics(keep_looking=True).line_for_round(2) == "I can move a little if you can come down a bit too."  # meet halfway comes first
    assert Tactics(keep_looking=True, meet_halfway=False).line_for_round(2) == "If we cannot agree on a price, I will keep looking at other listings."


# ---------------------------------------------------------------- every playbook sentence is safe on its own


@pytest.mark.parametrize("move_id", ["quantity", "refer", "again", "decide_today", "extras", "best_price", "meet_halfway", "keep_looking"])
def test_every_move_sentence_passes_the_fact_checker_rules(move_id):
    t = Tactics(**ALL_ON)
    sentence = t.moves()[move_id].sentence
    f = facts(**ALL_ON)
    assert blocked(sentence, f) == set(), (move_id, sentence)


@pytest.mark.parametrize("move_id", ["quantity", "refer", "again", "decide_today", "keep_looking"])
def test_the_claims_get_checked_if_the_buyer_did_not_approve_them(move_id):
    """Without approval these sentences are NOT trusted. Promises are blocked by the rules. The rest go to the model,
    which sees no approved note for them."""
    from app.agents.fact_sentences import residual_statements

    sentence = Tactics(**ALL_ON).moves()[move_id].sentence
    unapproved = facts()  # nothing approved, no trusted sentences
    if move_id == "quantity":
        assert blocked(sentence, unapproved) != set()  # a promise to buy two: the rules block it
    else:
        assert residual_statements(sentence, unapproved) == [sentence]  # not safe, so the model must judge it
    assert Tactics(**ALL_ON).moves()[move_id].note not in unapproved.approved_notes  # and no approved note to lean on


def test_an_approved_sentence_cannot_carry_extra_words_past_the_check():
    from app.agents.fact_checker import without_approved_sentences

    f = facts(**ALL_ON)
    f = f.model_copy(update={"approved_sentences": Tactics(**ALL_ON).persuasion_lines()})
    exact = "If we agree a good price, I would buy two. Could you do $651?"
    assert without_approved_sentences(exact, f) == "Could you do $651?"
    padded = "If we agree a good price, I would buy two and tell everyone about you. Could you do $651?"
    assert "tell everyone" in without_approved_sentences(padded, f)  # not an exact match, so it stays and gets checked


def test_matching_is_not_fooled_by_case_or_spacing_but_is_exact_otherwise():
    from app.agents.fact_checker import without_approved_sentences

    f = facts(**ALL_ON).model_copy(update={"approved_sentences": ["If we agree a good price, I would buy two."]})
    assert without_approved_sentences("if we agree  a GOOD price, I would buy two.", f) == ""
    assert without_approved_sentences("If we agree a good price, I would buy three.", f) != ""
