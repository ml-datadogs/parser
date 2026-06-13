from __future__ import annotations

from typing import Any

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from scraper.sites.registry import get_site
from scraper.spiders.base import BaseSpider

# Default in-flight request cap when a site routes through the Bright Data Web
# Unlocker. PAYG Web Unlocker has unlimited concurrency, so throughput should be
# bound by how many slow server-side solves run in parallel, not an arbitrary
# cap. Overridable per environment via BRIGHTDATA_UNLOCKER_CONCURRENCY.
DEFAULT_UNLOCKER_CONCURRENCY = 128


class GenericSiteSpider(CrawlSpider, BaseSpider):
    """Config-driven spider: scrapy crawl generic -a site=<name>."""

    name = "generic"

    def __init__(self, site: str | None = None, *args, **kwargs):
        if not site:
            raise ValueError(
                "Pass -a site=<name>, e.g. scrapy crawl generic -a site=quotes"
            )
        site_pkg = get_site(site)
        self.site_config = site_pkg.config
        self.site_name = site
        self.allowed_domains = list(self.site_config.allowed_domains)
        self.start_urls = list(self.site_config.start_urls)
        self._site_custom_settings = self.site_config.custom_settings()
        super().__init__(*args, **kwargs)

        rules = self._build_rules(self.site_config)
        self.rules = rules
        self._compile_rules()

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        settings = dict(spider._site_custom_settings)
        if spider._unlocker_active(crawler.settings):
            settings.update(spider._unlocker_settings(crawler.settings))
        for key, value in settings.items():
            crawler.settings.set(key, value, priority="spider")
        return spider

    def _unlocker_active(self, settings) -> bool:
        """True when this site's requests route through the Bright Data Web
        Unlocker (an API token is configured *and* the site defines an
        ``unlocker_zone``). Mirrors ``BrightDataUnlockerMiddleware``."""
        return bool(
            settings.get("BRIGHTDATA_API_TOKEN")
            and getattr(self.site_config, "unlocker_zone", None)
        )

    @staticmethod
    def _unlocker_settings(settings) -> dict[str, Any]:
        """Settings that override the residential-tuned site config when the Web
        Unlocker is active.

        With the Unlocker every request is rewritten to ``api.brightdata.com``
        and billed per call, while anti-bot and IP rotation are solved
        server-side. That invalidates the residential politeness/retry tuning:

        - A 404 is now genuine (not exit-IP cloaking), so retrying it just bills
          for a missing page repeatedly. Drop 404 and cut the retry count.
        - All traffic shares one host, so the per-domain cap and autothrottle
          (whose delay tracks the slow server-side solve latency, not load) only
          throttle throughput. Disable them and let concurrency bound throughput.
        """
        concurrency = settings.getint(
            "BRIGHTDATA_UNLOCKER_CONCURRENCY", DEFAULT_UNLOCKER_CONCURRENCY
        )
        return {
            "RETRY_HTTP_CODES": [403, 429, 500, 502, 503, 504],
            "RETRY_TIMES": 2,
            "AUTOTHROTTLE_ENABLED": False,
            "DOWNLOAD_DELAY": 0,
            "CONCURRENT_REQUESTS": concurrency,
            # One host (api.brightdata.com): keep the per-domain cap from
            # bottlenecking the global concurrency above.
            "CONCURRENT_REQUESTS_PER_DOMAIN": concurrency,
            # Server-side solves can be slow; give them headroom.
            "DOWNLOAD_TIMEOUT": 120,
        }

    @classmethod
    def update_settings(cls, settings):
        CrawlSpider.update_settings(settings)

    def start_requests(self):
        proxy_meta = self.site_config.proxy_meta()
        for url in self.site_config.start_urls:
            yield scrapy.Request(
                url, callback=self.parse_start_url, meta=dict(proxy_meta)
            )

    def parse_start_url(self, response, **kwargs):
        # ``start_requests`` dispatches start URLs straight to this callback,
        # bypassing CrawlSpider's ``parse_with_rules`` (which both parses and
        # follows links). Without following links here, pagination and lot links
        # that only appear on the start pages are never crawled - so a scoped
        # crawl of an auction would stop at catalog page 1. Apply the rules
        # explicitly so start pages are followed like any other page.
        yield from self.parse_item(response)
        yield from self._requests_to_follow(response)

    def _build_request(self, rule, link):
        request = super()._build_request(rule, link)
        request.meta.update(self.site_config.proxy_meta())
        return request

    def raw_item_from_response(self, response):
        item = super().raw_item_from_response(response)
        item["spider"] = self.site_config.name
        return item

    def _build_rules(self, config):
        link_rules = config.link_rules
        extractor_kwargs = {}
        if link_rules.allow:
            extractor_kwargs["allow"] = list(link_rules.allow)
        if link_rules.deny:
            extractor_kwargs["deny"] = list(link_rules.deny)
        if link_rules.restrict_css:
            extractor_kwargs["restrict_css"] = list(link_rules.restrict_css)

        return (
            Rule(
                LinkExtractor(**extractor_kwargs),
                callback="parse_item",
                follow=True,
            ),
        )

    def parse_item(self, response):
        yield self.raw_item_from_response(response)
