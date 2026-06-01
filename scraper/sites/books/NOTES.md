# books.toscrape.com

## Page types

- **Catalog listing** (`/` and `/catalogue/page-N.html`): product grid with pagination.
- **Category listing** (`/catalogue/category/books/<slug>/index.html`): filtered product grid.
- **Book detail** (`/catalogue/<slug>_<id>/index.html`): single book page.

## Key selectors

| Field | Selector |
|-------|----------|
| Title | `article.product_pod h3 a::attr(title)` |
| Price | `article.product_pod p.price_color` |
| Availability | `article.product_pod p.instock.availability` |
| Rating | `article.product_pod p.star-rating` (class encodes rating) |
| Next page | `li.next a::attr(href)` |

## Pagination

Follow `li.next a` links in the product listing sidebar.

## Proxy / anti-bot

Demo site with no anti-bot. No special Bright Data zone required for development.

## Crawl entry

```bash
scrapy crawl generic -a site=books
```

## Parse entry

```bash
python -m scraper.parse --site books
```
