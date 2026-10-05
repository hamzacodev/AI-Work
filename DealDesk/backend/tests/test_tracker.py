import ast
from pathlib import Path

import pytest

from app.negotiation.tracker import (
    VendorState,
    best_offer,
    leverage_for,
    others_active,
    summarize,
)

V = VendorState


def deal():
    return [V("a", "Alpha", 840), V("b", "Beta", 650), V("c", "Gamma", 870)]


def test_the_best_offer_is_the_lowest_price():
    assert best_offer(deal()).vendor_id == "b"


def test_blocked_vendors_and_vendors_without_a_price_never_count():
    states = [V("a", "Alpha", 300, status="blocked"), V("b", "Beta"), V("c", "Gamma", 700)]
    assert best_offer(states).vendor_id == "c"
    assert best_offer([V("a", "Alpha")]) is None


def test_a_tie_goes_to_the_vendor_listed_first():
    assert best_offer([V("a", "A", 650), V("b", "B", 650)]).vendor_id == "a"


def test_an_offer_far_below_the_market_is_not_credible_but_is_not_hidden():
    states = [V("a", "Alpha", 200), V("b", "Beta", 650)]
    assert best_offer(states, median=700).vendor_id == "b"
    s = summarize(states, 700)
    assert s.best.vendor_id == "b" and s.ranking[0].vendor_id == "a" and s.ranking[0].warning and s.warnings


def test_your_example_400_beats_500_and_600():
    states = [V("a", "A", 500), V("b", "B", 600), V("c", "C", 400)]
    assert best_offer(states, median=700).vendor_id == "c"


# ---------------------------------------------------------------- leverage: a number, never a name


def test_leverage_is_the_best_price_of_the_others_when_it_is_lower_than_this_vendors_price():
    assert leverage_for("a", deal(), 700, 760) == 650
    assert leverage_for("c", deal(), 700, 760) == 650


def test_the_best_vendor_gets_no_leverage_from_a_higher_price():
    assert leverage_for("b", deal(), 700, 760) is None  # the others are all higher: telling Beta would raise its price


def test_leverage_ignores_the_vendors_own_price():
    assert leverage_for("b", [V("b", "Beta", 650), V("a", "Alpha", 900)], 700, 760) is None


def test_leverage_may_be_above_the_market_and_the_ceiling_because_it_is_a_real_price():
    states = [V("a", "Alpha", 900), V("b", "Beta", 780)]
    assert leverage_for("a", states, 700, 760) == 780  # a fact another vendor gave, not an offer from us
    assert leverage_for("a", [V("a", "Alpha", 700), V("b", "Beta", 780)], 700, 760) is None  # but never a price higher than this vendor's own


def test_no_leverage_from_a_blocked_or_far_too_low_offer():
    assert leverage_for("a", [V("a", "A", 800), V("b", "B", 500, status="blocked")], 700, 760) is None
    assert leverage_for("a", [V("a", "A", 800), V("b", "B", 100)], 700, 760) is None  # a 100 dollar "offer" is a trap


def test_no_leverage_for_a_vendor_without_a_price_or_unknown():
    assert leverage_for("a", [V("a", "A"), V("b", "B", 600)], 700, 760) is None
    assert leverage_for("zzz", deal(), 700, 760) is None


def test_leverage_is_only_a_number():
    assert isinstance(leverage_for("a", deal(), 700, 760), (int, float))  # the result is a plain number, no name


# ---------------------------------------------------------------- the hold rule and the summary


def test_others_active_means_someone_else_is_still_negotiating():
    states = [V("a", "A", 600), V("b", "B", 650, status="paused"), V("c", "C", 700, status="blocked")]
    assert not others_active("a", states)
    assert others_active("b", states)  # Alpha is still negotiating
    assert others_active("a", [*states, V("d", "D", status="negotiating")])


def test_summary_names_the_best_deal_and_the_savings():
    states = [V("a", "Alpha", 840, "paused", "firm_price", True), V("b", "Beta", 630, "paused", "firm_price", True), V("c", "Gamma", 620, "paused")]
    s = summarize(states, 700)
    assert s.best.name == "Gamma" and s.best.price == 620
    assert s.saved == 80 and s.saved_pct == pytest.approx(11.4)
    assert [r.name for r in s.ranking] == ["Gamma", "Beta", "Alpha"]
    assert s.all_done and s.still_negotiating == 0
    assert "Gamma" in s.headline and "$620" in s.headline and "You decide" in s.headline


def test_summary_says_when_vendors_are_still_negotiating():
    s = summarize([V("a", "A", 650), V("b", "B", 700)], 700)
    assert not s.all_done and s.still_negotiating == 2 and "Still negotiating with 2 vendors" in s.headline


def test_summary_is_honest_when_the_best_offer_is_not_below_the_market():
    s = summarize([V("a", "A", 750, "paused")], 700)
    assert s.saved == -50 and "not below the market" in s.headline


def test_summary_with_no_prices():
    s = summarize([V("a", "A")], 700)
    assert s.best is None and s.saved is None and "No vendor" in s.headline


def test_the_tracker_imports_no_ai_or_network_library():
    tree = ast.parse(Path("app/negotiation/tracker.py").read_text())
    names = {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    names |= {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not names & {"openai", "httpx", "requests", "aiohttp", "supabase", "langgraph"}


# ---------------------------------------------------------------- waking up paused vendors


def test_a_paused_vendor_is_woken_when_another_vendor_gets_lower():
    from app.negotiation.tracker import reengage_candidates

    states = [V("a", "A", 650, "paused", "good_price", rounds=2), V("b", "B", 630, "negotiating")]
    assert reengage_candidates(states, 700, 760, 3) == ["a"]


def test_a_vendor_is_not_woken_for_a_number_we_already_told_them():
    from app.negotiation.tracker import reengage_candidates

    states = [V("a", "A", 650, "paused", "good_price", rounds=2, last_leverage=630), V("b", "B", 630)]
    assert reengage_candidates(states, 700, 760, 3) == []


def test_firm_round_limit_and_blocked_vendors_are_never_woken():
    from app.negotiation.tracker import reengage_candidates

    best = V("b", "B", 600)
    for v in (
        V("a", "A", 650, "paused", "round_limit", rounds=3),
        V("a", "A", 650, "blocked"),
        V("a", "A", 650, "paused", "good_price", rounds=3),  # no rounds left
    ):
        assert reengage_candidates([v, best], 700, 760, 3) == []


def test_a_vendor_who_said_no_or_final_is_written_to_again_when_another_vendor_gets_a_lower_price():
    from app.negotiation.tracker import reengage_candidates

    best = V("b", "B", 600)
    for reason in ("refused", "firm_price"):
        assert reengage_candidates([V("a", "A", 650, "paused", reason, rounds=2), best], 700, 760, 6) == ["a"]
