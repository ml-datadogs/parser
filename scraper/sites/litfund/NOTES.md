# litfund.ru (Аукционный дом «Литфонд»)

Auction house with two entities crawled into a single `parsed_items` stream,
distinguished by a `type` discriminator (`"auction"` | `"item"`) and linked via
`auction_id`.

## Page types

- **Auctions index** (`/auction/`): entry point, links out to auction catalogs.
- **Auction catalog** (`/auction/<auction_id>/`, paginated via `?page=N`):
  auction header + grid of lot cards. `auction_id` may be alphanumeric
  (`750`, `739.2`, `593s2`, `700s1`).
- **Lot / item** (`/auction/<auction_id>/<lot_number>/`): single lot detail.

`auction_id` and `lot_number` are derived from the canonical
`meta[property="og:url"]` (falls back to the request URL), which is reliable on
both page types regardless of how the page was reached.

## Key selectors

### Item / lot page

| Field | Selector |
|-------|----------|
| ids | `meta[property="og:url"]` -> `/auction/<id>/<lot>/` |
| Title | `h5[data-lf-microdata="lot-name"]` (fallback `meta[property="og:title"]`) |
| Lot index | `h2[data-lf-microdata="lot-index"]` ("Лот 20") |
| Description | `[data-lf-microdata="lot-desc"]` (fallback `meta[property="og:description"]`) |
| Start price | `[data-lf-microdata="lot-start-price"]` ("500 000") |
| Final price | `.tm-product-price-final` (completed lots only) |
| Views | `[data-type="lot-views-cnt"]` |
| Images | `a[data-lf-microdata="lot-image"]::attr(href)` (fallback `meta[property="og:image"]`) |

### Auction catalog page

| Field | Selector |
|-------|----------|
| id | `meta[property="og:url"]` |
| Number | `div.uk-display-inline-block small` (1st), regex `№\s*([\d.]+)` then strip `.` |
| Date | `div.uk-display-inline-block small` (2nd) |
| Status | "completed" if "Аукцион завершён" present, else `[data-online$="-t-to-start"]` ("Через 4 дня") |
| Title / category | `section h4` (fallback `meta[property="og:title"]`) |
| Description | `meta[property="og:description"]` (absent on some active auctions) |
| Lot links (crawl) | `article.tm-product-card a.tm-media-box::attr(href)` |
| Pagination (crawl) | `ul.uk-pagination a::attr(href)` -> `?page=N` |

## Completed vs active auctions

- Completed: status label `span.uk-label-danger` "Аукцион завершён"; lots carry
  a final price ("Финальная ставка" / "Продан за").
- Active/upcoming: number header appends ". Аукцион сезона"; status is a
  countdown label (`-t-to-start`); lots have no final price yet.

Always present: `auction_id`, lot `title`, `start_price`, `views`, `images`.
Optional: `final_price`, auction `description`.

## Pagination

Catalog pages are walked via `?page=N` links extracted from `ul.uk-pagination`.

## Proxy / anti-bot

Russian-language site; routed through Bright Data with `proxy_country="ru"` and
`download_delay=1.0` to stay polite across the large archive (~750+ auctions,
~220k lots). Validate on a single auction (e.g. `388`) before crawling the full
archive.

## Crawl entry

```bash
scrapy crawl generic -a site=litfund
```

## Parse entry

```bash
python -m scraper.parse --site litfund
```
