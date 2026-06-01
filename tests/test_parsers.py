from pathlib import Path

import pytest

from scraper.sites.registry import get_site


@pytest.mark.parametrize("site_name", ["quotes", "books"])
def test_parse_fixture_listing(site_name: str):
    site = get_site(site_name)
    assert site.parse is not None

    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "scraper"
        / "sites"
        / site_name
        / "fixtures"
        / "listing.html"
    )
    body = fixture_path.read_bytes()
    records = site.parse(body, f"https://{site_name}.example/listing")

    assert len(records) > 0
    if site_name == "quotes":
        assert "text" in records[0]
        assert "author" in records[0]
        assert records[0]["author"]
    else:
        assert "title" in records[0]
        assert "price" in records[0]
        assert records[0]["title"]
