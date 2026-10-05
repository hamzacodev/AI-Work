

def test_the_densest_group_keeps_one_version_of_an_item_when_prices_split():
    from app.research.pricing import Offer, densest_group

    mk = lambda i, p: Offer(p, f"https://s{i}.example.com/x", "t", "US")
    offers = [mk(i, p) for i, p in enumerate([999, 1050, 1100, 1585, 1600])]
    kept, dropped = densest_group(offers)
    assert [o.price for o in kept] == [999, 1050, 1100] and len(dropped) == 2


def test_the_densest_group_changes_nothing_when_there_is_no_clear_group():
    from app.research.pricing import Offer, densest_group

    mk = lambda i, p: Offer(p, f"https://s{i}.example.com/x", "t", "US")
    offers = [mk(i, p) for i, p in enumerate([300, 700, 1500, 3000])]
    kept, dropped = densest_group(offers)
    assert len(kept) == 4 and dropped == []
