from __future__ import annotations

import re

from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import Rule

from scraper.spiders.generic import GenericSiteSpider


class LitfundAuctionsSpider(GenericSiteSpider):
    """Scoped litfund refresh: crawl only the given auctions (catalog pages + lots).

    Unlike the ``generic`` litfund crawl (which starts from the newest auction
    and follows links across the whole archive), this spider is constrained to
    an explicit list of auction ids so a single auction can be re-fetched on
    demand without pulling the entire site.

    Usage:
        scrapy crawl litfund_auctions -a auctions=747,752

    Skip lot pages already stored in ClickHouse ``raw_items`` (catalog and
    pagination pages are always re-fetched so new lots are still discovered):
        scrapy crawl litfund_auctions -a auctions=747,752 -a skip_existing=1

    Disable the Bright Data proxy for a direct fetch by clearing the creds:
        scrapy crawl litfund_auctions -a auctions=747,752 \\
            -s BRIGHTDATA_CUSTOMER= -s BRIGHTDATA_ZONE= -s BRIGHTDATA_PASSWORD=
    """

    name = "litfund_auctions"

    def __init__(
        self,
        auctions: str = "747,752",
        skip_existing: str = "0",
        *args,
        **kwargs,
    ):
        self._auction_ids = [a.strip() for a in auctions.split(",") if a.strip()]
        if not self._auction_ids:
            raise ValueError("Pass -a auctions=<id>[,<id>...], e.g. 747,752")
        self.skip_existing = str(skip_existing).lower() in {"1", "true", "yes"}
        ids = "|".join(re.escape(a) for a in self._auction_ids)
        self._lot_url_re = re.compile(
            rf"^https?://(?:www\.)?litfund\.ru/auction/(?:{ids})/\d+[a-z]?/$"
        )
        self._existing_lot_urls: set[str] | None = None
        super().__init__(site="litfund", *args, **kwargs)
        # Scrapy 2.13+ drives the crawl from ``start_urls`` (the inherited
        # ``start_requests`` is no longer consulted), so scope the entry points
        # to the requested auctions here, after the base __init__ sets 757.
        self.start_urls = [
            f"https://www.litfund.ru/auction/{auction_id}/"
            for auction_id in self._auction_ids
        ]

    def _build_rules(self, config):
        ids = "|".join(re.escape(a) for a in self._auction_ids)
        allow = (
            rf"/auction/(?:{ids})/$",
            rf"/auction/(?:{ids})/\d+[a-z]?/$",
            rf"/auction/(?:{ids})/\?page=\d+",
        )
        return (
            Rule(
                LinkExtractor(
                    allow=list(allow),
                    allow_domains=list(config.allowed_domains),
                ),
                callback="parse_item",
                follow=True,
                process_request=self._skip_fetched_lots,
            ),
        )

    def _skip_fetched_lots(self, request, response):
        """Drop lot-detail requests already stored in ClickHouse (opt-in).

        Catalog and pagination pages always pass through so newly added lots
        are still discovered on re-runs.
        """
        if not self.skip_existing:
            return request
        if not self._lot_url_re.match(request.url):
            return request
        if request.url in self._load_existing_lot_urls():
            return None
        return request

    def _load_existing_lot_urls(self) -> set[str]:
        if self._existing_lot_urls is not None:
            return self._existing_lot_urls

        settings = self.crawler.settings
        host = settings.get("CLICKHOUSE_HOST", "")
        if not host:
            self.logger.warning(
                "skip_existing requested but CLICKHOUSE_HOST is not set; "
                "nothing will be skipped."
            )
            self._existing_lot_urls = set()
            return self._existing_lot_urls

        try:
            import clickhouse_connect

            client = clickhouse_connect.get_client(
                host=host,
                port=settings.getint("CLICKHOUSE_PORT", 8123),
                username=settings.get("CLICKHOUSE_USER", "default"),
                password=settings.get("CLICKHOUSE_PASSWORD", ""),
                database=settings.get("CLICKHOUSE_DATABASE", "scraper"),
            )
            try:
                table = settings.get("CLICKHOUSE_RAW_TABLE", "raw_items")
                result = client.query(
                    f"SELECT DISTINCT url FROM {table} "
                    "WHERE spider = 'litfund' "
                    "AND http_status = 200 "
                    "AND match(url, %(pattern)s)",
                    parameters={"pattern": self._lot_url_re.pattern},
                )
                self._existing_lot_urls = {row[0] for row in result.result_rows}
            finally:
                client.close()
        except Exception as exc:
            self.logger.warning(
                "skip_existing: failed to load fetched lot urls from ClickHouse "
                "(%s); nothing will be skipped.",
                exc,
            )
            self._existing_lot_urls = set()
            return self._existing_lot_urls

        self.logger.info(
            "skip_existing: %d lot pages already in ClickHouse will be skipped.",
            len(self._existing_lot_urls),
        )
        return self._existing_lot_urls
