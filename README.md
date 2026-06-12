# Multi-site Scrapy scraper

Python + Scrapy scraper that routes requests through **Bright Data** residential proxies and stores **raw-first** page payloads in **ClickHouse**. Structured parsing runs as a separate incremental worker.

## Architecture

```text
sites/<name>/          Per-site package (config, parser, fixtures, NOTES.md)
    |
    v
GenericSiteSpider / custom spiders  -->  RawItem
    |
    +--> BrightDataProxyMiddleware
    +--> JsonLinesExportPipeline (local output/)
    +--> ClickHouseRawPipeline (raw_items)
    |
    v
python -m scraper.parse  -->  parsed_items (ReplacingMergeTree)
```

- **Raw-first**: crawlers store full HTML; parsing is decoupled and replayable.
- **ClickHouse** holds append-only raw data and idempotent parsed output.
- **Postgres** is intentionally not used here (reserved for crawl state / serving layer later).

## Quick start

Install [uv](https://docs.astral.sh/uv/), then:

```bash
uv sync --dev
cp .env.example .env
```

Run a demo crawl without proxy or ClickHouse:

```bash
uv run scrapy crawl generic -a site=quotes
# output/generic.jsonl is written locally
```

List spiders:

```bash
uv run scrapy list
```

## Bright Data proxy

1. Create a residential proxy zone in the [Bright Data control panel](https://brightdata.com/cp/zones).
2. Copy customer ID, zone name, and password into `.env`:

```env
BRIGHTDATA_CUSTOMER=your_customer_id
BRIGHTDATA_ZONE=your_zone
BRIGHTDATA_PASSWORD=your_password
BRIGHTDATA_COUNTRY=us
```

Proxy URL format:

```text
http://brd-customer-<CUSTOMER>-zone-<ZONE>[-country-<CC>]:<PASSWORD>@brd.superproxy.io:33335
```

For production HTTPS targets, install the [Bright Data SSL certificate](https://docs.brightdata.com/general/account/ssl-certificate) and set `BRIGHTDATA_VERIFY_SSL=true`.

Per-site proxy overrides are supported via `SiteConfig.proxy_zone` / `proxy_country`.

## ClickHouse setup

Start ClickHouse locally:

```bash
docker compose up -d clickhouse
```

Apply DDL:

```bash
clickhouse-client --multiquery < sql/raw_items.sql
clickhouse-client --multiquery < sql/parsed_items.sql
clickhouse-client --multiquery < sql/parse_state.sql
clickhouse-client --multiquery < sql/litfund_items.sql
clickhouse-client --multiquery < sql/litfund_metrics.sql
```

Configure `.env`:

```env
CLICKHOUSE_HOST=localhost
CLICKHOUSE_DATABASE=scraper
```

Crawl with raw landing enabled:

```bash
uv run scrapy crawl generic -a site=quotes
```

Parse raw rows incrementally:

```bash
uv run python -m scraper.parse --site quotes
uv run python -m scraper.parse --site quotes --reset
```

## Litfund: refresh the latest auctions

Scrape the litfund archive for the most recent auctions, skip the ones already
stored as completed in ClickHouse, then crawl and parse the rest in one command:

```bash
uv run python -m scraper.litfund --latest 20
```

- Discovers ids from `/auction/archives/?y=&k=&page=N` (newest-first).
- Skips auctions already saved as `completed`; re-crawls ones still `upcoming`.
- Flags: `--dry-run`, `--no-parse`, `--no-skip-existing-lots`, `--max-pages`.

Requires Bright Data and ClickHouse configured in `.env` (the parse/skip steps
are disabled and all discovered auctions are crawled when `CLICKHOUSE_HOST` is
empty).

### Litfund crawl metrics

`sql/litfund_metrics.sql` defines read-only views over `raw_items` and
`parsed_items` for data-count estimation and crawl-process health (no extra
writes):

- `scraper.litfund_data_overview` - single-row counts: auctions (by status),
  total lots, avg/max lots per auction, auctions with/without lots, a rough
  `estimated_total_lots`, and `last_parsed_at`.
- `scraper.litfund_auction_coverage` - one row per auction: status, lots
  parsed, pages fetched, HTTP errors, and last fetched/parsed timestamps;
  surfaces auctions that were fetched but yielded few/zero lots.
- `scraper.litfund_crawl_health_daily` - per fetch-day fetch volume, error
  rate, and lot/catalog/other page mix.
- `scraper.litfund_crawl_health_overall` - lifetime rollup of the same health
  signals plus first/last fetch timestamps.

```bash
clickhouse-client -q "SELECT * FROM scraper.litfund_data_overview FORMAT Vertical"
clickhouse-client -q "SELECT * FROM scraper.litfund_crawl_health_overall FORMAT Vertical"
```

## Adding a new site

Create a package under `scraper/sites/<name>/`:

```text
scraper/sites/mysite/
  __init__.py      # export config (+ optional parse)
  config.py        # SiteConfig
  parser.py        # optional parse(body, url) -> list[dict]
  NOTES.md         # site structure / selectors / quirks
  fixtures/        # saved HTML for offline parser development
```

Run it:

```bash
uv run scrapy crawl generic -a site=mysite
uv run python -m scraper.parse --site mysite
```

For sites that do not fit the generic link rules, add a hand-written spider under `scraper/spiders/custom/`.

## Fixture capture

Fetch a live page through Bright Data and save it as a fixture:

```bash
uv run python -m scraper.capture --site quotes --url https://quotes.toscrape.com/ --name listing
```

## Docker

```bash
docker compose up --build scraper
```

## Tests

```bash
uv run pytest
```

## Project layout

```text
pyproject.toml         Project metadata and dependencies (managed by uv)
uv.lock                Locked dependency versions
scraper/
  middlewares.py       Bright Data proxy middleware
  pipelines.py         JSONL export + ClickHouse raw pipeline
  sites/               Per-site packages
  spiders/             generic + custom spiders
  parse/               Incremental parse worker CLI
  capture/             Fixture capture CLI
sql/                   ClickHouse DDL
tests/                 Offline unit tests
```
