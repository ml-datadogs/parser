import re
from pathlib import Path

from scrapy.http import HtmlResponse
from scrapy.linkextractors import LinkExtractor

from scraper.sites.registry import get_site, list_sites


def test_list_sites_includes_demo_sites():
    sites = list_sites()
    assert "quotes" in sites
    assert "books" in sites


def test_litfund_is_registered():
    site = get_site("litfund")
    assert site.config.name == "litfund"
    assert site.config.allowed_domains == ("litfund.ru", "www.litfund.ru")
    assert site.parse is not None


def test_litfund_auction_link_extraction():
    """The config link rules must discover every lot and every catalog page
    of an auction. Auction 752 page 1 has 36 lots and paginates to page 7."""
    config = get_site("litfund").config
    fixture = (
        Path(__file__).resolve().parents[1]
        / "scraper"
        / "sites"
        / "litfund"
        / "fixtures"
        / "auction.html"
    )
    response = HtmlResponse(
        url="https://www.litfund.ru/auction/752/",
        body=fixture.read_bytes(),
        encoding="utf-8",
    )
    extractor = LinkExtractor(
        allow=list(config.link_rules.allow),
        allow_domains=list(config.allowed_domains),
    )
    urls = {link.url for link in extractor.extract_links(response)}

    lot_urls = {u for u in urls if re.search(r"/auction/752/\d+/$", u)}
    page_urls = {u for u in urls if "page=" in u}

    assert len(lot_urls) == 36
    assert page_urls == {
        f"https://www.litfund.ru/auction/752/?page={n}" for n in range(2, 8)
    }


def test_get_site_returns_config_and_parser():
    site = get_site("quotes")
    assert site.config.name == "quotes"
    assert site.config.allowed_domains == ("quotes.toscrape.com",)
    assert site.parse is not None


def test_site_config_custom_settings():
    site = get_site("quotes")
    settings = site.config.custom_settings()
    assert settings["ROBOTSTXT_OBEY"] is True
    assert settings["DOWNLOAD_DELAY"] == 0.5
