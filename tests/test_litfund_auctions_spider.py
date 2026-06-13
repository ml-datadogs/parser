from scraper.spiders.custom.litfund_auctions import LitfundAuctionsSpider


def test_non_heal_requires_auctions():
    import pytest

    with pytest.raises(ValueError):
        LitfundAuctionsSpider(auctions="", heal="0")


def test_non_heal_builds_catalog_start_urls():
    spider = LitfundAuctionsSpider(auctions="716,717")
    assert spider.start_urls == [
        "https://www.litfund.ru/auction/716/",
        "https://www.litfund.ru/auction/717/",
    ]
    # Catalog crawl: one follow rule is installed.
    assert len(spider.rules) == 1


def test_heal_mode_allows_no_auctions_and_disables_following():
    spider = LitfundAuctionsSpider(heal="1", auctions="")
    assert spider.heal is True
    # No catalog crawl / link-following in heal mode.
    assert spider.rules == ()
    # Pattern matches any litfund lot URL when unscoped.
    assert spider._lot_url_re.match("https://www.litfund.ru/auction/709s1/55/")
    assert not spider._lot_url_re.match("https://www.litfund.ru/auction/709s1/")


def test_heal_start_requests_seed_missing_lots(monkeypatch):
    spider = LitfundAuctionsSpider(heal="1", auctions="716")
    missing = [
        "https://www.litfund.ru/auction/716/90/",
        "https://www.litfund.ru/auction/716/96/",
    ]
    monkeypatch.setattr(spider, "_load_lots_missing_data", lambda: missing)

    requests = list(spider.start_requests())

    assert [r.url for r in requests] == missing
    # Each seeded request parses the lot directly (no link extraction).
    assert all(r.callback == spider.parse_item for r in requests)
