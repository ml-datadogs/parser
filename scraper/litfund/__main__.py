from __future__ import annotations

import argparse
import logging
import os

import requests
from dotenv import load_dotenv

from scraper.capture.__main__ import _build_proxy_url
from scraper.middlewares import build_unlocker_request
from scraper.parse.worker import _get_client, _load_settings_from_env, run_parse_worker
from scraper.sites.litfund.discover import extract_auction_ids
from scraper.sites.registry import get_site

logger = logging.getLogger("litfund.latest")

ARCHIVE_URL = "https://www.litfund.ru/auction/archives/"
SITE = "litfund"


def _configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # basicConfig leaves its handler at NOTSET (emits every record). Scrapy's
    # CrawlerProcess later calls logging.root.setLevel(NOTSET) when it installs
    # its own handler, after which this NOTSET handler would print every DEBUG
    # record - including full page-body RawItem dumps ("Scraped from ... {'body':
    # b'...'}"). Pin the handler level so DEBUG stays filtered regardless.
    for handler in logging.getLogger().handlers:
        handler.setLevel(level)


def _fetch(url: str) -> str:
    """Fetch a litfund page, preferring the Web Unlocker over the residential proxy.

    litfund cloaks the residential pool with 404s on valid pages (the very
    reason the crawl spider routes through the Web Unlocker). Discovery must use
    the same path, or it 404s on the archive. When ``BRIGHTDATA_API_TOKEN`` and
    the site's ``unlocker_zone`` are set, go through the Unlocker API; otherwise
    fall back to the residential proxy.
    """
    config = get_site(SITE).config
    api_token = os.getenv("BRIGHTDATA_API_TOKEN", "")
    zone = getattr(config, "unlocker_zone", None)
    if api_token and zone:
        api_url = os.getenv(
            "BRIGHTDATA_API_URL", "https://api.brightdata.com/request"
        )
        payload, headers = build_unlocker_request(
            api_token=api_token, zone=zone, target_url=url
        )
        response = requests.post(api_url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        return response.text

    proxy_url = _build_proxy_url(SITE)
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    headers = {}
    if config.user_agent:
        headers["User-Agent"] = config.user_agent

    verify_ssl = os.getenv("BRIGHTDATA_VERIFY_SSL", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    response = requests.get(
        url, proxies=proxies, headers=headers, timeout=60, verify=verify_ssl
    )
    response.raise_for_status()
    return response.text


def discover_latest(n: int, *, max_pages: int = 10) -> list[str]:
    """Return up to ``n`` most-recent auction ids from the litfund archive.

    Walks ``/auction/archives/?y=&k=&page=N`` newest-first, stopping once ``n``
    distinct ids are collected, a page yields no new ids, or ``max_pages`` is hit.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        url = f"{ARCHIVE_URL}?y=&k=&page={page}"
        logger.debug("fetching archive page %d: %s", page, url)
        html = _fetch(url)
        new_on_page = 0
        for auction_id in extract_auction_ids(html):
            if auction_id not in seen:
                seen.add(auction_id)
                ordered.append(auction_id)
                new_on_page += 1
        if new_on_page == 0:
            logger.debug("page %d added no new auction ids; stopping", page)
            break
        if len(ordered) >= n:
            break
    return ordered[:n]


def _stored_auction_ids(*, completed_only: bool) -> set[str] | None:
    """Auction ids already stored for litfund, or None if no DB is configured.

    When ``completed_only`` is True, only auctions stored as ``completed`` are
    returned (the default skip set, so ``upcoming`` auctions get re-crawled to
    fill final prices). When False, every auction already present in
    ``parsed_items`` is returned, regardless of status.
    """
    if not os.getenv("CLICKHOUSE_HOST", ""):
        return None

    settings = _load_settings_from_env()
    client = _get_client(settings)
    try:
        status_filter = (
            "AND JSONExtractString(toString(fields), 'status') = 'completed'"
            if completed_only
            else ""
        )
        result = client.query(
            f"""
            SELECT DISTINCT JSONExtractString(toString(fields), 'auction_id')
            FROM {settings["parsed_table"]}
            WHERE spider = 'litfund'
              AND JSONExtractString(toString(fields), 'type') = 'auction'
              {status_filter}
            """
        )
        return {row[0] for row in result.result_rows if row[0]}
    finally:
        client.close()


def _run_crawl(to_crawl: list[str], *, skip_existing: bool) -> None:
    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.project import get_project_settings

    settings = get_project_settings()
    # Scrapy defaults to DEBUG, which dumps every scraped RawItem (including the
    # full page body) to the log. Run at INFO so progress stays readable; honor
    # LOG_LEVEL for opt-in verbosity.
    settings.set(
        "LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO").upper(), priority="cmdline"
    )
    # install_root_handler=False: keep the logging handler configured in
    # _configure_logging() instead of letting Scrapy add its own (which also
    # resets the root logger to NOTSET). Our handler is pinned to LOG_LEVEL, so
    # this keeps the crawl at INFO and avoids duplicated lines / DEBUG body dumps.
    process = CrawlerProcess(settings, install_root_handler=False)
    process.crawl(
        "litfund_auctions",
        auctions=",".join(to_crawl),
        skip_existing="1" if skip_existing else "0",
    )
    process.start()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Discover the latest N litfund auctions, skip those already stored as "
            "completed, then crawl and parse the rest."
        )
    )
    parser.add_argument(
        "--latest",
        type=int,
        required=True,
        help="Number of most-recent auctions to consider.",
    )
    parser.add_argument(
        "--no-parse",
        action="store_true",
        help="Crawl only; skip the parse worker step.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve the auctions to crawl, log them, and exit.",
    )
    parser.add_argument(
        "--no-skip-existing-lots",
        action="store_true",
        help="Re-fetch lot pages already stored in ClickHouse (default: skip them).",
    )
    parser.add_argument(
        "--skip-existing-auctions",
        action="store_true",
        help=(
            "Skip every auction already present in ClickHouse, not just those "
            "stored as completed (so upcoming auctions are not re-crawled)."
        ),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Safety cap on archive pages to walk while discovering (default: 10).",
    )
    args = parser.parse_args()

    if args.latest < 1:
        parser.error("--latest must be >= 1")

    _configure_logging()
    load_dotenv()

    candidates = discover_latest(args.latest, max_pages=args.max_pages)
    logger.info(
        "discovered %d latest auctions: %s",
        len(candidates),
        ", ".join(candidates) or "(none)",
    )
    if not candidates:
        logger.warning("no auctions discovered from the archive; nothing to do.")
        return

    stored = _stored_auction_ids(completed_only=not args.skip_existing_auctions)
    if stored is None:
        logger.warning(
            "CLICKHOUSE_HOST is not set; cannot determine already-parsed auctions, "
            "so all discovered auctions will be crawled and the parse step skipped."
        )
        to_crawl = candidates
    else:
        skipped = [a for a in candidates if a in stored]
        logger.info(
            "already in DB (%s), skipping (%d): %s",
            "any status" if args.skip_existing_auctions else "completed",
            len(skipped),
            ", ".join(skipped) or "(none)",
        )
        to_crawl = [a for a in candidates if a not in stored]

    if not to_crawl:
        logger.info("all discovered auctions are already in DB; nothing to crawl.")
        return

    logger.info("crawling %d auctions: %s", len(to_crawl), ", ".join(to_crawl))
    for index, auction_id in enumerate(to_crawl, start=1):
        logger.info("starting auction %s (%d/%d)", auction_id, index, len(to_crawl))

    if args.dry_run:
        logger.info("dry run: not crawling or parsing.")
        return

    _run_crawl(to_crawl, skip_existing=not args.no_skip_existing_lots)

    if args.no_parse:
        logger.info("crawl done; --no-parse set, skipping the parse worker.")
        return
    if stored is None:
        logger.info("crawl done; parse skipped because ClickHouse is not configured.")
        return

    logger.info("crawl done; running parse worker for site=%s", SITE)
    total = run_parse_worker(SITE)
    logger.info("parse done; %d records parsed for site=%s", total, SITE)


if __name__ == "__main__":
    main()
