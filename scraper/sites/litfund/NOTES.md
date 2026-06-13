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

Russian-language site; routed through Bright Data with `proxy_country="ru"`. The
residential pool cloaks valid pages as 404s regardless of exit IP, so set
`BRIGHTDATA_API_TOKEN` to route through the Web Unlocker (`unlocker_zone=
"litfund_unlocker"`), which solves anti-bot server-side. Without a token it
falls back to the residential proxy (`download_delay=0.25`, per-retry IP
rotation, 404 treated as retryable). Validate on a single auction (e.g. `388`)
before crawling the full archive.

### Cost when the Unlocker is active

Every Unlocker request is billed, so `GenericSiteSpider` retunes automatically:
404 is no longer retried, autothrottle/per-domain caps are off, and concurrency
rises to `BRIGHTDATA_UNLOCKER_CONCURRENCY` (default 128). To avoid re-paying for
pages:

- Prefer the bounded `litfund_auctions ... -a skip_existing=1` or
  `python -m scraper.litfund --latest N` (skips stored auctions/lots by default)
  over the unbounded `generic` full-archive crawl.
- Set `JOBDIR=<dir>` so an interrupted crawl resumes instead of refetching.

## Crawl entry

```bash
scrapy crawl generic -a site=litfund
```

Scoped re-fetch of specific auctions (catalog pages + lots), skipping lots
already stored (recommended under the billed Unlocker):

```bash
scrapy crawl litfund_auctions -a auctions=747,752 -a skip_existing=1
```

## Latest-N refresh

One command that scrapes the archive for the N most recent auctions, skips the
ones already stored as `completed` in ClickHouse, then crawls and parses the
rest. Re-crawls auctions we only have as `upcoming` so final prices get filled:

```bash
python -m scraper.litfund --latest 20
```

Discovery walks `/auction/archives/?y=&k=&page=N` (newest-first) until N ids are
collected. Useful flags: `--dry-run` (log the resolved ids and exit),
`--no-parse` (crawl only), `--no-skip-existing-lots`, `--max-pages`.

## Parse entry

```bash
python -m scraper.parse --site litfund
```

Auction start date is normalized in the parser to `date_iso` (ISO `YYYY-MM-DD`,
from the Russian `date` text) and surfaced as a real `auction_date` Date column
on the `litfund_items` view via a join on `auction_id`.

## Metrics

`sql/litfund_metrics.sql` defines read-only views (no extra writes) for
data-count estimation and crawl health:

- `litfund_data_overview` - single-row data-count estimate: auctions by status,
  total/avg/max lots, auctions with/without lots, `estimated_total_lots`,
  `last_parsed_at`. Answers "how much do we have?".
- `litfund_auction_coverage` - one row per auction (status, `lots_parsed`,
  `pages_fetched`, `http_errors`, last fetched/parsed). Spot auctions fetched
  but with few/zero parsed lots, or carrying HTTP errors.
- `litfund_crawl_health_daily` - per fetch-day volume, `error_rate`, and
  lot/catalog/other page mix. Answers "is the crawl healthy over time?".
- `litfund_crawl_health_overall` - lifetime rollup of the same health signals.

Page-type classification (lot vs catalog vs archive/other) is derived from the
`url` using the same auction/lot regex shape as `discover.py` and the
`litfund_auctions` spider.
