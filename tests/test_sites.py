from scraper.sites.registry import get_site, list_sites


def test_list_sites_includes_demo_sites():
    sites = list_sites()
    assert "quotes" in sites
    assert "books" in sites


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
