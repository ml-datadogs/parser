from __future__ import annotations

from parsel import Selector


def parse(body: bytes | str, url: str) -> list[dict]:
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = body

    selector = Selector(text=text)
    records: list[dict] = []
    for quote in selector.css("div.quote"):
        records.append(
            {
                "text": quote.css("span.text::text").get(default="").strip(),
                "author": quote.css("small.author::text").get(default="").strip(),
                "tags": quote.css("div.tags a.tag::text").getall(),
                "source_url": url,
            }
        )
    return records
