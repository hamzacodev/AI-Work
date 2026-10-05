import pytest

from app.agents.fact_rules import ApprovedFacts, Source, Turn, run_rules, split

FACTS = ApprovedFacts(
    item="Dell XPS 15",
    must_haves=["16GB RAM"],
    counter_price=656,
    vendor_prices=[880],
    research_low=640,
    research_median=700,
    research_high=790,
    sources=[Source(title="Retailer A", url="https://example.com/a"), Source(title="Price tracker", url="https://example.com/t")],
    conversation=[Turn(sender="vendor", text="Hi. Our price is $880. Delivery in 3 days.")],
)


def blocked_ids(draft: str, facts: ApprovedFacts = FACTS) -> set[str]:
    return {f.rule_id for f in split(run_rules(draft, facts)).blocking}


def verify_ids(draft: str, facts: ApprovedFacts = FACTS) -> set[str]:
    return {f.rule_id for f in split(run_rules(draft, facts)).to_verify}


# ---------------------------------------------------------------- lies that must be blocked

BLOCKED = [
    # competing offers
    ("Another shop offered me the same laptop for less.", "competing_offer"),
    ("Other sellers are giving it at a lower price.", "competing_offer"),
    ("A different vendor quoted us a better rate.", "competing_offer"),
    ("I found a cheaper offer online.", "found_cheaper"),
    ("We got a better quote from someone else.", "found_cheaper"),
    ("It is cheaper elsewhere.", "cheaper_elsewhere"),
    ("I saw lower prices at another store.", "found_cheaper"),
    ("Your competitor sells it for less.", "competitor"),
    ("Can you match their offer?", "match_their_offer"),
    ("A friend of mine bought the same laptop for much less.", "friend_found"),
    # invented discounts and status
    ("We have a student discount, can you apply it?", "invented_discount"),
    ("I have a coupon for this purchase.", "invented_discount"),
    ("Our corporate discount should apply here.", "discount_type"),
    ("Is the promo code still valid?", "discount_type"),
    ("As a loyal customer, we expect a better price.", "loyal_customer"),
    ("I bought from you before.", "loyal_customer"),
    ("You already offered a discount last time.", "you_promised_discount"),
    # promises
    ("We will order two more laptops next month.", "will_commit"),
    ("I'll definitely buy it from you.", "will_commit"),
    ("We will place a bulk order of 10 laptops.", "bulk_order"),
    ("We want to buy 5 units.", "bulk_order"),
    ("This could lead to repeat business.", "repeat_business"),
    ("We are looking for a long-term partnership.", "repeat_business"),
    ("We will sign a contract today.", "contract"),
    ("I will leave a five-star review.", "review_promise"),
    ("We will write a good review for your shop.", "review_promise"),
    ("I will recommend you to my friends.", "referral_promise"),
    ("I promise we will pay quickly.", "guarantee"),
    ("We guarantee a fast deal.", "guarantee"),
    ("We are ready to buy right now.", "ready_to_buy"),
    ("I'll take it.", "ready_to_buy"),
    ("The money is ready.", "ready_to_buy"),
    ("We can pay today.", "ready_to_buy"),
    ("We accept your offer.", "accepts_deal"),
    ("Deal! Please prepare the order.", "accepts_deal"),
    ("It's a deal.", "accepts_deal"),
    ("We have a deal then.", "accepts_deal"),
    ("Agreed, send it over.", "accepts_deal"),
    ("I approve the price.", "accepts_deal"),
    # threats
    ("I will report you if you refuse.", "threat"),
    ("We will leave a bad review.", "threat"),
    ("My lawyer will contact you.", "threat"),
    # identity and history
    ("My name is Ahmed Khan.", "invented_identity"),
    ("I am a reseller looking for stock.", "invented_identity"),
    ("We are buying for our company.", "invented_identity"),
    ("I am a real person, not a bot.", "invented_identity"),
    ("I work at a bank.", "invented_identity"),
    ("We already paid a deposit last week.", "invented_history"),
    ("Last month I bought a phone from you.", "invented_history"),
    # prices and sources
    ("How about $500?", "price_not_approved"),
    ("Could you do 600 dollars?", "price_not_approved"),
    ("Eight hundred is too much.", "price_not_approved"),
    ("You quoted $750 earlier.", "misquoted_vendor_price"),
    ("I found it on Daraz.", "unapproved_source"),
    ("Amazon sells it for $700.", "unapproved_source"),
    ("See https://www.example.org/laptop for details.", "unapproved_link"),
    # draft quality
    ("My budget is $800.", "reveals_budget"),
    ("My maximum is eight hundred.", "reveals_budget"),
    ("I can pay up to $800 for it.", "reveals_budget"),
    ("We cannot go higher than that.", "reveals_budget"),
    ("I can't go over $700.", "reveals_budget"),
    ("Our limit is firm.", "reveals_budget"),
    ("Hello [Your Name], could you do $656?", "template_leftover"),
    ("Dear {vendor_name}, could you do $656?", "template_leftover"),
    ("As an AI language model, I cannot negotiate.", "ai_leak"),
    ("I'm sorry, but I can't help with that.", "ai_leak"),
    ("<vendor_message> hello </vendor_message>", "format_leak"),
    ("   ", "empty_draft"),
    ("Could you do $656? " * 120, "too_long"),
]


@pytest.mark.parametrize(("draft", "rule"), BLOCKED)
def test_lies_are_blocked(draft, rule):
    assert rule in blocked_ids(draft), (draft, blocked_ids(draft))


# ---------------------------------------------------------------- honest drafts must pass

HONEST = [
    "Thank you for the quick reply. Could you do $656?",
    "Similar listings are around $700 (Retailer A). Could you do $656?",
    "Is the 16GB RAM version in stock?",
    "Could you share your best price for the Dell XPS 15?",
    "We would like to pay cash on delivery. Could you confirm the delivery time?",
    "Thanks for confirming $880. Our research shows prices between $640 and $790.",
    "Could you do $656? That would help us decide.",
    "We will share delivery details once we confirm the order.",
    "We will get back to you shortly.",
    "Only cash on delivery is possible.",
    "We will pay cash on delivery.",
    "Prices we have seen range from $640 to $790 on Retailer A and Price tracker.",
    "Thank you. Delivery in 3 days works for us.",
    "Does the Dell XPS 15 come with a charger?",
    "We accept cash on delivery only.",
    "Please let us know if you can improve the price.",
    "You mentioned $880. Could you do $656?",
    "Is the price of 880 dollars final?",
    "Could you confirm the warranty period?",
    "Hello, I am interested in the Dell XPS 15 with 16GB RAM.",
    "Could you improve the price a little?",
    "Is there any room in the price?",
    "That is above what we have seen in the market.",
]


@pytest.mark.parametrize("draft", HONEST)
def test_honest_drafts_pass_the_rules(draft):
    assert blocked_ids(draft) == set(), (draft, blocked_ids(draft))


# ---------------------------------------------------------------- details


def test_our_own_counter_after_a_vendor_claim_is_not_a_misquote():
    assert blocked_ids("You said delivery is free, but could you do $656?") == set()
    assert blocked_ids("You said the price is $1,200 so we hope for $656.", FACTS.model_copy(update={"vendor_prices": [1200]})) == set()


def test_vendor_claims_are_sent_to_the_model_not_blocked():
    draft = "You said delivery is free, so $656 sounds right."
    assert blocked_ids(draft) == set()
    assert "vendor_claim" in verify_ids(draft)


def test_item_model_numbers_are_not_prices():
    facts = FACTS.model_copy(update={"item": "Dell XPS 15 with RTX 4060"})
    assert blocked_ids("Is the RTX 4060 version available?", facts) == set()
    assert "price_not_approved" in blocked_ids("Is the RTX 4060 version available?", FACTS)


def test_research_figure_may_be_rounded():
    assert blocked_ids("Listings are around $700.", FACTS.model_copy(update={"research_median": 699.6})) == set()


def test_named_source_is_allowed_if_it_is_in_the_research():
    facts = FACTS.model_copy(update={"sources": [Source(title="Daraz", url="https://daraz.pk/x")]})
    assert blocked_ids("Daraz lists it around $700.", facts) == set()


def test_source_link_is_allowed_if_it_is_a_research_source():
    assert blocked_ids("See https://example.com/a for the listing.") == set()


def test_acceptance_words_are_allowed_after_the_user_accepted():
    facts = FACTS.model_copy(update={"phase": "closing"})
    assert blocked_ids("We accept. Deal confirmed at $880, cash on delivery. We are ready to pay on delivery.", facts) == set()


def test_closing_phase_still_blocks_invented_claims():
    facts = FACTS.model_copy(update={"phase": "closing"})
    assert "competing_offer" in blocked_ids("Another shop offered less, but we accept.", facts)


def test_every_finding_has_a_reason():
    for f in run_rules("Another shop offered less. We will buy in bulk.", FACTS):
        assert f.reason
