from __future__ import annotations

from parsel import Selector


def parse(body: bytes | str, url: str) -> list[dict]:
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = body

    selector = Selector(text=text)
    records: list[dict] = []
    for book in selector.css("article.product_pod"):
        records.append(
            {
                "title": book.css("h3 a::attr(title)").get(default="").strip(),
                "price": book.css("p.price_color::text").get(default="").strip(),
                "availability": book.css("p.instock.availability::text").re_first(
                    r"\S+"
                ),
                "rating": book.css("p.star-rating::attr(class)").re_first(
                    r"star-rating (\w+)"
                ),
                "source_url": url,
            }
        )
    return records
