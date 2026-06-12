from __future__ import annotations

import re
from typing import Any

from parsel import Selector

# Real auction ids are numeric, optionally with a session suffix: 757, 671s1, 739.2.
# This excludes utility pages under /auction/ (archives, rules, calendar, ...).
# Lot numbers are usually numeric but may carry a letter suffix (e.g. 84a).
_AUCTION_URL_RE = re.compile(
    r"/auction/(?P<auction>\d+(?:[.s]\d+)?)/(?:(?P<lot>\d+[a-z]?)/)?"
)
_NUMBER_RE = re.compile(r"№\s*([\d.]+)")
_WS_RE = re.compile(r"\s+")

_RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_RU_DATE_RE = re.compile(
    r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", re.IGNORECASE
)


def _parse_ru_date(text: str) -> str | None:
    """Normalize a Russian date like "11 июня 2026 года" to ISO "2026-06-11".

    Returns ``None`` when the day/month/year cannot be recognized.
    """
    if not text:
        return None
    match = _RU_DATE_RE.search(text)
    if not match:
        return None
    day, month_word, year = match.groups()
    month = _RU_MONTHS.get(month_word.lower())
    if month is None:
        return None
    return f"{int(year):04d}-{month:02d}-{int(day):02d}"


def _to_text(value: str | None) -> str:
    if not value:
        return ""
    return _WS_RE.sub(" ", value.replace("\xa0", " ")).strip()


def _ids_from_url(url: str) -> tuple[str | None, str | None]:
    match = _AUCTION_URL_RE.search(url or "")
    if not match:
        return None, None
    return match.group("auction"), match.group("lot")


def _parse_lot(
    selector: Selector, auction_id: str | None, lot_number: str | None, url: str
) -> dict[str, Any]:
    title = _to_text(selector.css('[data-lf-microdata="lot-name"]::text').get())
    if not title:
        title = _to_text(selector.css('meta[property="og:title"]::attr(content)').get())

    description = _to_text(
        " ".join(selector.css('[data-lf-microdata="lot-desc"] ::text').getall())
    )
    if not description:
        description = _to_text(
            selector.css('meta[property="og:description"]::attr(content)').get()
        )

    start_price = _to_text(
        selector.css('[data-lf-microdata="lot-start-price"]::text').get()
    )
    final_price = _to_text(
        " ".join(selector.css(".tm-product-price-final::text").getall())
    )
    views = _to_text(selector.css('[data-type="lot-views-cnt"]::text').get())

    images = selector.css('a[data-lf-microdata="lot-image"]::attr(href)').getall()
    if not images:
        images = selector.css('meta[property="og:image"]::attr(content)').getall()

    record: dict[str, Any] = {
        "type": "item",
        "auction_id": auction_id,
        "lot_number": lot_number,
        "lot_index": _to_text(
            selector.css('[data-lf-microdata="lot-index"]::text').get()
        ),
        "title": title,
        "description": description,
        "start_price": start_price,
        "views": views,
        "images": images,
        "source_url": url,
    }
    if final_price:
        record["final_price"] = final_price
    return record


def _parse_card_prices(card: Selector) -> dict[str, Any]:
    """Extract the price rows from a lot card.

    The price block is a flat sequence of alternating label/value divs. Which
    rows are present depends on auction state: active lots expose a "Лидирующая
    ставка" (leading bid), completed lots a "Финальная ставка" (final price)
    that may carry an "НДР" badge meaning the bid did not reach the reserve.
    Pairing by label text is more robust than the per-state CSS classes.
    """
    result: dict[str, Any] = {}
    rows = card.css(".tm-product-card-prices > div")
    index = 0
    while index < len(rows):
        row = rows[index]
        if "uk-text-meta" not in (row.attrib.get("class", "")):
            index += 1
            continue
        label = _to_text(" ".join(row.css("::text").getall()))
        value = ""
        if index + 1 < len(rows):
            value = _to_text(" ".join(rows[index + 1].css("::text").getall()))
        if label.startswith("Стартовая"):
            result["start_price"] = value
        elif label.startswith("Лидирующая"):
            result["leading_bid"] = value
        elif label.startswith("Финальная"):
            result["final_price"] = value
            result["reserve_not_met"] = bool(row.css(".tm-product-card-ndr"))
        index += 2
    return result


def _parse_lot_card(
    card: Selector, auction_id: str | None, page_url: str
) -> dict[str, Any] | None:
    lot_url = (
        card.css("a.tm-media-box::attr(href)").get()
        or card.css("h3.tm-product-card-title a::attr(href)").get()
    )
    _, lot_number = _ids_from_url(lot_url or "")

    title = _to_text(card.css("h3.tm-product-card-title a::text").get())
    lot_index = _to_text(card.css(".uk-text-meta.uk-margin-xsmall-bottom::text").get())
    prices = _parse_card_prices(card)
    views = _to_text(card.css('[data-type="lot-views-cnt"]::text').get())
    images = card.css("figure.tm-media-box-wrap img::attr(src)").getall()

    record: dict[str, Any] = {
        "type": "item",
        "auction_id": auction_id,
        "lot_number": lot_number,
        "lot_index": lot_index,
        "title": title,
        "start_price": prices.get("start_price", ""),
        "views": views,
        "images": images,
        "source_url": lot_url or page_url,
    }
    if "leading_bid" in prices:
        record["leading_bid"] = prices["leading_bid"]
    if "final_price" in prices:
        record["final_price"] = prices["final_price"]
        record["reserve_not_met"] = prices["reserve_not_met"]
    return record


def _parse_auction(
    selector: Selector, auction_id: str | None, url: str
) -> dict[str, Any]:
    header_smalls = selector.css("div.uk-display-inline-block small")
    number = ""
    date = ""
    if header_smalls:
        number_match = _NUMBER_RE.search(
            _to_text(" ".join(header_smalls[0].css("::text").getall()))
        )
        if number_match:
            number = number_match.group(1).rstrip(".")
        if len(header_smalls) > 1:
            date = _to_text(" ".join(header_smalls[1].css("::text").getall()))

    page_text = " ".join(selector.css("::text").getall())
    if "Аукцион завершён" in page_text:
        status = "completed"
    else:
        status = (
            _to_text(selector.css('[data-online$="-t-to-start"]::text').get())
            or "upcoming"
        )

    title = _to_text(selector.css("section h4::text").get())
    if not title:
        title = _to_text(selector.css('meta[property="og:title"]::attr(content)').get())

    description = _to_text(
        selector.css('meta[property="og:description"]::attr(content)').get()
    )

    return {
        "type": "auction",
        "auction_id": auction_id,
        "number": number,
        "date": date,
        "date_iso": _parse_ru_date(date) or "",
        "status": status,
        "title": title,
        "description": description,
        "source_url": url,
    }


def parse(body: bytes | str, url: str) -> list[dict]:
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = body

    selector = Selector(text=text)

    canonical = selector.css('meta[property="og:url"]::attr(content)').get() or url
    auction_id, lot_number = _ids_from_url(canonical)
    if auction_id is None:
        auction_id, lot_number = _ids_from_url(url)

    if auction_id is None:
        return []

    if lot_number is not None:
        return [_parse_lot(selector, auction_id, lot_number, url)]

    records: list[dict] = [_parse_auction(selector, auction_id, url)]
    for card in selector.css("article.tm-product-card"):
        item = _parse_lot_card(card, auction_id, url)
        if item is not None:
            records.append(item)
    return records
