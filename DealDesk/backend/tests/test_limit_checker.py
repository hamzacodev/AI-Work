import ast
from pathlib import Path

import pytest

from app.guardrails.limit_checker import (
    Context,
    DealLimits,
    check_decision,
    check_outgoing,
    compute_ceiling,
)

VENDOR = "sales@techhub.example.com"
ADDRESS = "12 Example Street, Block 5, Gulshan, Karachi"
PHONE = "+92 300 1234567"


def ctx(**over) -> Context:
    base = {
        "max_price": 800,
        "recipient": VENDOR,
        "vendor_contacts": frozenset({VENDOR, "other@vendor.example.com"}),
        "vendor_offer": 880,
        "vendor_prices": (880,),
        "research_figures": (640, 700, 790),
        "address": ADDRESS,
        "phone": PHONE,
    }
    base.update(over)
    return Context(**base)


def check(message: str, **over):
    return check_outgoing(message, ctx(**over))


def codes(result) -> list[str]:
    return [v.split(":")[0] for v in result.violations]


# ---------- the ceiling ----------


@pytest.mark.parametrize(
    ("maximum", "ratio", "expected"),
    [(800, 0.95, 760.0), (5, 0.95, 4.75), (799.99, 0.95, 759.99), (1000, 0.9, 900.0), (100, 1.0, 100.0)],
)
def test_ceiling_rounds_down(maximum, ratio, expected):
    assert compute_ceiling(maximum, ratio) == expected


def test_ceiling_is_always_below_the_maximum():
    for m in (1, 7.5, 99, 800, 12345.67):
        assert compute_ceiling(m) < m


# ---------- normal messages ----------


def test_counter_message_is_allowed():
    r = check("Thank you. Could you do $656?", counter_price=656, previous_counter=None)
    assert r.allowed and r.violations == []


def test_message_with_no_price_is_allowed():
    assert check("Thank you. Please share your best price.").allowed


def test_item_and_spec_numbers_are_not_prices():
    assert check("Is the Dell XPS 15 with 16GB RAM and a 512GB SSD still available?").allowed


def test_item_model_number_can_be_whitelisted():
    assert not check("Is the RTX 4060 version available?").allowed
    assert check("Is the RTX 4060 version available?", known_numbers=frozenset({4060.0})).allowed


# ---------- the counter rules ----------


def test_counter_equal_to_the_ceiling_is_allowed():
    assert check("Could you do $760?", counter_price=760).allowed


def test_counter_above_the_ceiling_is_blocked():
    r = check("Could you do $770?", counter_price=770)
    assert "counter_above_ceiling" in codes(r)


def test_counter_equal_to_the_maximum_is_blocked():
    r = check("Could you do $800?", counter_price=800)
    assert not r.allowed
    assert "counter_above_ceiling" in codes(r)


def test_counter_must_be_below_the_vendors_offer():
    r = check("Could you do $880?", counter_price=880, vendor_offer=880)
    assert "counter_not_below_vendor_offer" in codes(r)


def test_counter_must_not_move_down():
    r = check("Could you do $600?", counter_price=600, previous_counter=650)
    assert "counter_below_previous" in codes(r)


def test_counter_must_be_positive():
    assert "counter_not_positive" in codes(check("Could you do $0?", counter_price=0))


# ---------- every price must be an approved price ----------


def test_vendors_own_price_can_be_repeated_even_above_the_maximum():
    assert check("You said $880.", counter_price=None).allowed


def test_invented_price_is_blocked():
    r = check("I found it for $500 elsewhere.", counter_price=656)
    assert "price_not_allowed" in codes(r)


def test_research_figures_may_be_quoted():
    assert check("Similar listings are around $700.", counter_price=656).allowed


def test_research_figure_may_be_rounded():
    assert check("Similar listings are around $700.", research_figures=(699.6,)).allowed


def test_research_figure_next_to_the_maximum_is_dropped():
    r = check("Prices go up to $799.", research_figures=(640, 700, 799))
    assert not r.allowed


def test_two_prices_both_checked():
    r = check("Could you do $656 or even $400?", counter_price=656)
    assert "price_not_allowed" in codes(r)


# ---------- the maximum must never leak ----------


@pytest.mark.parametrize(
    "message",
    [
        "My budget is $800.",
        "I can pay 800 usd.",
        "Up to 800.00 please.",
        "My limit is eight hundred dollars.",
        "My limit is 0.8k.",
        "I can go to $0.8k.",
        "Not more than USD 800.",
        "Budget: 800",
    ],
)
def test_maximum_price_leaks_are_blocked(message):
    r = check(message, counter_price=656)
    assert "max_price_leak" in codes(r), r.violations


def test_walk_away_price_leaks_are_blocked():
    r = check("The lowest I would accept is $780.", counter_price=656, walk_away_prices=(780,))
    assert "max_price_leak" in codes(r)


def test_repeating_the_maximum_is_fine_if_the_vendor_said_it_first():
    r = check("You mentioned $800, thank you.", vendor_prices=(800, 880))
    assert r.allowed


# ---------- address and phone ----------


def test_address_is_blocked_before_accept():
    r = check("We are at 12 Example Street, Karachi.")
    assert "private_address_leak" in codes(r)


def test_part_of_the_address_is_also_blocked():
    assert "private_address_leak" in codes(check("Please deliver to Gulshan."))


@pytest.mark.parametrize("text", ["Call +92 300 1234567", "Call 0300 1234567", "Call 03001234567", "Call 300-1234567"])
def test_phone_is_blocked_before_accept(text):
    assert "private_phone_leak" in codes(check(text))


def test_closing_message_to_the_accepted_vendor_may_include_address_and_phone():
    msg = f"Price confirmed at $696, cash on delivery. Address: {ADDRESS}. Phone: {PHONE}. Please share the order number."
    r = check(msg, phase="closing", accepted_contact=VENDOR, vendor_prices=(696,), vendor_offer=696)
    assert r.allowed, r.violations


def test_closing_message_to_a_different_vendor_may_not_include_the_address():
    other = "other@vendor.example.com"
    r = check(f"Deliver to {ADDRESS}", phase="closing", accepted_contact=other)
    assert "private_address_leak" in codes(r)


def test_closing_phase_without_an_accepted_vendor_gives_no_access():
    assert "private_address_leak" in codes(check(f"Deliver to {ADDRESS}", phase="closing", accepted_contact=None))


# ---------- payment tricks ----------


@pytest.mark.parametrize(
    "message",
    [
        "We will send an advance payment.",
        "I can pay by bank transfer.",
        "Let me wire the money.",
        "I will pay a deposit first.",
        "I can send a gift card.",
        "I can pay in crypto.",
        "Paying with Bitcoin works.",
        "Use Western Union.",
        "I'll send it through JazzCash.",
        "Easypaisa is fine, I'll pay upfront.",
    ],
)
def test_payment_commitments_are_blocked(message):
    assert "payment_not_allowed" in codes(check(message))


@pytest.mark.parametrize(
    "message",
    [
        "We cannot pay in advance. Only cash on delivery is possible.",
        "No advance payment, please. Cash on delivery only.",
        "Advance payment is not possible.",
        "We do not pay a deposit. Cash on delivery works for us.",
        "Payment will be cash on delivery.",
    ],
)
def test_refusing_prepayment_and_cash_on_delivery_are_allowed(message):
    assert check(message).allowed


def test_negation_from_a_different_sentence_does_not_count():
    r = check("No problem. We will pay in advance.")
    assert "payment_not_allowed" in codes(r)


# ---------- recipient, rounds, real sending ----------


def test_recipient_must_be_in_the_vendor_list():
    assert "recipient_not_in_vendor_list" in codes(check("Hello", recipient="stranger@evil.example.com"))


def test_recipient_match_ignores_case_and_spaces():
    assert check("Hello", recipient=" Sales@TechHub.Example.com ").allowed


def test_round_cap():
    assert check("Hello", rounds=3, max_rounds=3).allowed
    assert "round_cap_exceeded" in codes(check("Hello", rounds=4, max_rounds=3))


def test_real_sending_is_off_by_default():
    assert "real_send_disabled" in codes(check("Hello", sending_for_real=True))


def test_real_sending_needs_an_allowlisted_address():
    r = check("Hello", sending_for_real=True, real_send_enabled=True, owner_allowlist=frozenset({"me@mine.example.com"}))
    assert "real_send_not_allowlisted" in codes(r)


def test_real_sending_to_the_owner_is_allowed_when_enabled():
    r = check("Hello", sending_for_real=True, real_send_enabled=True, owner_allowlist=frozenset({VENDOR}))
    assert r.allowed


def test_simulated_sending_does_not_need_the_allowlist():
    assert check("Hello", sending_for_real=False, real_send_enabled=False).allowed


def test_all_violations_are_reported_together():
    r = check(f"I will wire $800 to {ADDRESS}", recipient="stranger@evil.example.com")
    assert {"recipient_not_in_vendor_list", "max_price_leak", "private_address_leak", "payment_not_allowed"} <= set(codes(r))


# ---------- user decisions ----------

LIMITS = DealLimits(max_price=800)


def test_accept_at_or_below_the_maximum():
    assert check_decision("accept", 696, LIMITS).allowed
    assert check_decision("accept", 800, LIMITS).allowed


def test_accept_above_the_maximum_needs_confirmation():
    r = check_decision("accept", 801, LIMITS)
    assert not r.allowed and r.requires_confirmation


def test_accept_above_the_maximum_with_confirmation_is_the_users_right():
    assert check_decision("accept", 900, LIMITS, confirm_over_limit=True).allowed


def test_the_ai_can_never_accept():
    r = check_decision("accept", 600, LIMITS, actor="ai")
    assert not r.allowed and not r.requires_confirmation
    assert not check_decision("accept", 900, LIMITS, confirm_over_limit=True, actor="ai").allowed


def test_user_counter_up_to_the_ceiling_is_allowed():
    assert check_decision("counter", 760, LIMITS).allowed


def test_user_counter_above_the_ceiling_needs_confirmation():
    r = check_decision("counter", 761, LIMITS)
    assert not r.allowed and r.requires_confirmation
    assert check_decision("counter", 790, LIMITS, confirm_over_limit=True).allowed


def test_reject_is_always_allowed():
    assert check_decision("reject", None, LIMITS).allowed


@pytest.mark.parametrize(("action", "price"), [("accept", None), ("accept", 0), ("counter", -5), ("counter", None)])
def test_decisions_need_a_positive_price(action, price):
    r = check_decision(action, price, LIMITS)
    assert not r.allowed and not r.requires_confirmation


def test_unknown_action_is_refused():
    assert not check_decision("negotiate", 500, LIMITS).allowed


# ---------- the guardrails stay free of AI and network code ----------

BANNED = {
    "openai", "anthropic", "httpx", "requests", "aiohttp", "urllib3", "urllib", "http", "socket",
    "langgraph", "langchain", "supabase", "tavily", "groq", "ollama", "app.core.llm", "app.core.db",
}  # fmt: skip


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_guardrails_import_no_llm_or_network_code():
    folder = Path(__file__).resolve().parent.parent / "app" / "guardrails"
    files = list(folder.glob("*.py"))
    assert len(files) >= 3  # the test must really look at the files
    for f in files:
        for name in _imports(f):
            root = name.split(".")[0]
            assert name not in BANNED and root not in BANNED, f"{f.name} imports {name}"
