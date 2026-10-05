import pytest

from app.guardrails.prices import extract_prices, numbers_in


def values(text: str, ignore=frozenset()) -> list[float]:
    return sorted(p.value for p in extract_prices(text, ignore))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$800", [800]),
        ("$1,200.50", [1200.5]),
        ("800 usd", [800]),
        ("800 USD", [800]),
        ("USD 800", [800]),
        ("PKR 220,000", [220000]),
        ("Rs. 150000", [150000]),
        ("Rs.150000", [150000]),
        ("rs 1,50,000", [150000]),
        ("12,50,000 rupees", [1250000]),
        ("£650", [650]),
        ("€700", [700]),
        ("AED 2,900", [2900]),
        ("800usd", [800]),
        ("800.00", [800]),
        ("I can do 790", [790]),
        ("between $700 and $750", [700, 750]),
    ],
)
def test_digit_prices(text, expected):
    assert values(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.5k", [1500]),
        ("$1.5k", [1500]),
        ("$0.8k", [800]),
        ("2 lakh", [200000]),
        ("1.5 lakh rupees", [150000]),
        ("3 million", [3000000]),
        ("2 lakh and fifty thousand", [50000, 200000]),
    ],
)
def test_scaled_prices(text, expected):
    assert values(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("eight hundred", [800]),
        ("five hundred dollars", [500]),
        ("twelve hundred", [1200]),
        ("one thousand two hundred fifty", [1250]),
        ("two lakh rupees", [200000]),
        ("Eight Hundred Dollars", [800]),
        ("fifty dollars", [50]),
        ("one hundred and fifty", [150]),
    ],
)
def test_prices_written_in_words(text, expected):
    assert values(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Do you have 16GB RAM?",
        "Dell XPS 15 with 16GB RAM",
        "Intel i7-13700H",
        "512GB SSD",
        "3 years warranty",
        "2026-10-02",
        "the 15 inch screen",
        "one moment please",
        "a 144Hz display",
        "delivery in 3 days",
        "20% off",
        "Thank you, please share your best price.",
    ],
)
def test_not_prices(text):
    assert values(text) == []


def test_item_numbers_can_be_ignored_but_currency_prices_cannot():
    assert values("RTX 4060 laptop") == [4060]
    assert values("RTX 4060 laptop", ignore=frozenset({4060.0})) == []
    assert values("RTX 4060 for $4060", ignore=frozenset({4060.0})) == [4060]


def test_numbers_in_item_text():
    assert numbers_in("Dell XPS 15 RTX 4060 16GB RAM") >= {15.0, 4060.0}
