import pytest

from app.research.pricing import (
    Offer,
    clean_offers,
    compute,
    confidence_level,
    domain,
    remove_outliers,
    spread,
)


def offer(price, url="https://shop-a.example.com/x", region="USA", condition="new", title="t") -> Offer:
    return Offer(price=price, url=url, title=title, region=region, condition=condition)


def many(prices, regions=("USA",)):
    return [offer(p, f"https://shop{i}.example.com/p", regions[i % len(regions)]) for i, p in enumerate(prices)]


# ---------------------------------------------------------------- cleaning


def test_offers_without_a_usable_link_are_dropped():
    bad = [offer(700, url=""), offer(700, url="ftp://x"), offer(700, url="not a url")]
    assert clean_offers(bad) == []


def test_non_positive_prices_are_dropped():
    assert clean_offers([offer(0), offer(-5)]) == []


@pytest.mark.parametrize("condition", ["used", "refurbished"])
def test_used_and_refurbished_are_dropped_when_new_is_wanted(condition):
    assert clean_offers([offer(500, condition=condition)]) == []


def test_unknown_condition_is_kept():
    assert len(clean_offers([offer(700, condition="unknown")])) == 1


def test_new_prices_are_dropped_when_the_buyer_wants_used():
    kept = clean_offers([offer(500, condition="used"), offer(900, "https://b.example.com/p", condition="new")], "used")
    assert [o.price for o in kept] == [500]


def test_duplicate_links_are_removed_even_with_a_trailing_slash():
    kept = clean_offers([offer(700, "https://a.example.com/p"), offer(701, "https://A.example.com/p/")])
    assert len(kept) == 1


def test_domain_ignores_www_and_case():
    assert domain("https://WWW.Shop.Example.com/a?b=1") == "shop.example.com"


# ---------------------------------------------------------------- outliers


def test_an_accessory_price_among_laptops_is_removed():
    kept, dropped = remove_outliers(many([699, 715, 640, 790, 95]))
    assert 95 not in [o.price for o in kept] and [o.price for o in dropped] == [95]


def test_an_inflated_bundle_price_is_removed():
    _, dropped = remove_outliers(many([700, 710, 690, 705, 4000]))
    assert [o.price for o in dropped] == [4000]


def test_normal_spread_is_untouched():
    kept, dropped = remove_outliers(many([640, 700, 715, 790]))
    assert len(kept) == 4 and dropped == []


def test_with_two_prices_nothing_is_removed():
    kept, dropped = remove_outliers(many([700, 95]))
    assert len(kept) == 2 and dropped == []


def test_the_second_test_removes_a_moderate_outlier_when_there_is_enough_data():
    # 1020 is inside the +/-50% band around the median, but far from a tight group
    kept, _ = remove_outliers(many([700, 702, 705, 708, 710, 712, 1020]))
    assert 1020 not in [o.price for o in kept]


# ---------------------------------------------------------------- the numbers


def test_low_median_high_are_computed_from_the_kept_offers():
    s = compute(many([640, 700, 715, 790]))
    assert (s.low, s.median, s.high) == (640, 707.5, 790)


def test_sources_are_counted_by_website_not_by_listing():
    offers = [offer(700, "https://a.example.com/1"), offer(710, "https://a.example.com/2"), offer(720, "https://b.example.com/1")]
    assert compute(offers).n_sources == 2


def test_regions_are_listed_once_and_sorted():
    s = compute(many([700, 710, 720, 730], regions=("UK", "USA")))
    assert s.regions == ["UK", "USA"]


def test_nothing_to_compute_gives_none():
    assert compute([]) is None


def test_spread_is_the_gap_over_the_median():
    assert spread(640, 700, 790) == pytest.approx(150 / 700)


# ---------------------------------------------------------------- confidence (CLAUDE.md section 11)


@pytest.mark.parametrize(
    ("sources", "regions", "spread_value", "expected"),
    [
        (3, 2, 0.10, "high"),
        (3, 2, 0.25, "high"),  # exactly at the limit
        (3, 2, 0.26, "medium"),  # just over
        (3, 1, 0.10, "medium"),  # one region only
        (2, 2, 0.10, "medium"),  # only two sources
        (2, 1, 0.50, "medium"),
        (1, 1, 0.0, "low"),  # one source
        (0, 0, 0.0, "low"),
        (4, 3, 0.61, "low"),  # the prices disagree too much
        (5, 3, 0.60, "medium"),
    ],
)
def test_confidence_levels(sources, regions, spread_value, expected):
    assert confidence_level(sources, regions, spread_value) == expected


def test_a_worked_example_end_to_end():
    kept, _ = remove_outliers(clean_offers(many([699, 715, 640, 790, 95], regions=("USA", "UK"))))
    s = compute(kept)
    # 4 websites, 2 regions, spread 21% (under the 25% limit): that is "high" confidence
    assert (s.low, s.high, s.n_sources, s.confidence) == (640, 790, 4, "high")


def test_two_groups_of_prices_are_all_kept_not_all_thrown_away():
    # the median (about 1,600) sits in the gap, so every price is outside the band. That is disagreement, not outliers.
    kept, dropped = remove_outliers(many([700, 705, 2500, 2600]))
    assert len(kept) == 4 and dropped == []
    assert confidence_level(4, 1, spread(700, 1602.5, 2600)) == "low"


def test_a_real_outlier_is_still_removed_when_most_prices_agree():
    kept, dropped = remove_outliers(many([700, 705, 710, 2600]))
    assert [o.price for o in dropped] == [2600] and len(kept) == 3
