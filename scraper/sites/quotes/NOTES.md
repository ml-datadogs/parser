# quotes.toscrape.com

## Page types

- **Listing** (`/` and `/page/N/`): grid of quote cards with pagination via `li.next`.
- **Tag listing** (`/tag/<tag>/` and paginated variants): same card layout filtered by tag.
- **Author detail** (`/author/<slug>/`): author bio plus their quotes.

## Key selectors

| Field | Selector |
|-------|----------|
| Quote text | `div.quote span.text` |
| Author | `div.quote small.author` |
| Tags | `div.quote div.tags a.tag` |
| Next page | `li.next a::attr(href)` |

## Pagination

Follow `li.next a` links until absent.

## Proxy / anti-bot

Demo site with no anti-bot. No special Bright Data zone required for development.

## Crawl entry

```bash
scrapy crawl generic -a site=quotes
```

## Parse entry

```bash
python -m scraper.parse --site quotes
```
