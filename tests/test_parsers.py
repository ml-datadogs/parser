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


def _litfund_fixture(name: str) -> bytes:
    return (
        Path(__file__).resolve().parents[1]
        / "scraper"
        / "sites"
        / "litfund"
        / "fixtures"
        / name
    ).read_bytes()


def test_litfund_parses_auction():
    site = get_site("litfund")
    records = site.parse(
        _litfund_fixture("auction.html"), "https://www.litfund.ru/auction/752/"
    )

    auction = records[0]
    assert auction["type"] == "auction"
    assert auction["auction_id"] == "752"
    assert auction["number"] == "752"
    assert auction["title"]
    assert auction["date"]
    assert auction["date_iso"] == "2026-06-11"

    items = [r for r in records if r["type"] == "item"]
    assert len(items) == 36
    assert all(item["auction_id"] == "752" for item in items)

    first = items[0]
    assert first["lot_number"] == "1"
    assert first["title"]
    assert first["start_price"]


@pytest.mark.parametrize(
    "page",
    [
        "auction_p2",
        "auction_p3",
        "auction_p4",
        "auction_p5",
        "auction_p6",
        "auction_p7",
    ],
)
def test_litfund_parses_catalog_pages(page: str):
    site = get_site("litfund")
    records = site.parse(
        _litfund_fixture(f"{page}.html"),
        f"https://www.litfund.ru/auction/752/?{page.split('_p')[1]}",
    )

    items = [r for r in records if r["type"] == "item"]
    assert len(items) > 0
    assert all(item["auction_id"] == "752" for item in items)
    assert all(item["lot_number"] for item in items)
    assert all(item["title"] for item in items)


def test_litfund_parses_completed_auction():
    site = get_site("litfund")
    records = site.parse(
        _litfund_fixture("auction_completed.html"),
        "https://www.litfund.ru/auction/747/",
    )

    auction = records[0]
    assert auction["type"] == "auction"
    assert auction["auction_id"] == "747"
    assert auction["number"] == "747"
    assert auction["status"] == "completed"
    assert auction["title"]

    items = [r for r in records if r["type"] == "item"]
    assert len(items) == 36
    assert all(item["auction_id"] == "747" for item in items)
    assert all(item["final_price"] for item in items)
    assert all(isinstance(item["reserve_not_met"], bool) for item in items)
    assert any(item["reserve_not_met"] for item in items)
    assert any(not item["reserve_not_met"] for item in items)


@pytest.mark.parametrize(
    "page",
    [
        "auction_completed_p2",
        "auction_completed_p3",
        "auction_completed_p4",
        "auction_completed_p5",
    ],
)
def test_litfund_parses_completed_catalog_pages(page: str):
    site = get_site("litfund")
    records = site.parse(
        _litfund_fixture(f"{page}.html"),
        f"https://www.litfund.ru/auction/747/?page={page.split('_p')[-1]}",
    )

    items = [r for r in records if r["type"] == "item"]
    assert len(items) > 0
    assert all(item["auction_id"] == "747" for item in items)
    assert all(item["lot_number"] for item in items)
    assert all(item["final_price"] for item in items)
    assert all("reserve_not_met" in item for item in items)


def test_litfund_parses_item():
    site = get_site("litfund")
    records = site.parse(
        _litfund_fixture("lot.html"), "https://www.litfund.ru/auction/752/2/"
    )

    assert len(records) == 1
    item = records[0]
    assert item["type"] == "item"
    assert item["auction_id"] == "752"
    assert item["lot_number"] == "2"
    assert item["title"]
    assert item["start_price"]
    assert item["views"]
    assert item["images"]
