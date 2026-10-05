import pytest

from app.agents.fact_rules import ApprovedFacts, Source, Turn
from app.agents.fact_sentences import is_safe, residual_statements, split_sentences

F = ApprovedFacts(
    item="Dell XPS 15",
    must_haves=["16GB RAM"],
    counter_price=656,
    vendor_prices=[880],
    research_low=640,
    research_median=700,
    research_high=790,
    sources=[Source(title="Retailer A", url="https://example.com/a"), Source(title="Price tracker", url="https://example.com/t")],
    conversation=[Turn(sender="vendor", text="Hi. Our price is $880. Delivery takes 3 days.")],
)

SAFE = [
    "Could you do $656?",
    "Is the 16GB RAM version in stock?",
    "Does the laptop come with a charger and a warranty card?",
    "Thank you for the quick reply.",
    "Thanks.",
    "Hello,",
    "Best regards",
    "We will share delivery details once we confirm the order.",
    "Only cash on delivery is possible for us.",
    "Payment will be cash on delivery.",
    "We will get back to you shortly.",
    "Similar listings are around $700 (Retailer A).",
    "Similar listings range from $640 to $790.",
    "Prices we have seen range from $640 to $790 on Retailer A.",
    "Our research shows prices between $640 and $790.",
    "Listings on Price tracker are around $700.",
    "We can offer $656.",
    "Our counter offer is $656.",
    "You mentioned $880 and delivery in 3 days.",
    "You said the price is $880.",
]


@pytest.mark.parametrize("sentence", SAFE)
def test_these_need_no_model(sentence):
    assert is_safe(sentence, F), sentence


NOT_SAFE = [
    "A friend across town told us the same laptop is selling for far less.",
    "Thank you, our friend got it for less.",  # a polite start must not hide a claim
    "Prices at the shop across the road are around $700.",  # research wording with an invented source
    "We can offer $880.",  # the counter template only covers OUR counter price
    "You mentioned the laptop comes with a free docking station.",
    "The screen is OLED.",
    "We have more purchases lined up.",
    "Thanks, and we found it cheaper elsewhere.",
    "Similar listings are around $700 and your reviews are bad.",
]


@pytest.mark.parametrize("sentence", NOT_SAFE)
def test_these_must_reach_the_model(sentence):
    assert not is_safe(sentence, F), sentence


def test_splitting_keeps_questions_and_statements_apart():
    assert split_sentences("Thanks. Is it new? We can offer $656!") == ["Thanks.", "Is it new?", "We can offer $656!"]


def test_a_fully_safe_draft_has_nothing_left_for_the_model():
    assert residual_statements("Thank you for the quick reply. Could you do $656?", F) == []


def test_only_the_risky_sentence_is_left():
    left = residual_statements("Thanks. A friend told us it is cheaper elsewhere. Could you do $656?", F)
    assert left == ["A friend told us it is cheaper elsewhere."]


def test_echoing_the_vendor_with_new_words_is_not_safe():
    assert not is_safe("You mentioned $880 and a free mouse.", F)
