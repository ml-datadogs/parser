from __future__ import annotations

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from scraper.sites.registry import get_site
from scraper.spiders.base import BaseSpider


class GenericSiteSpider(CrawlSpider, BaseSpider):
    """Config-driven spider: scrapy crawl generic -a site=<name>."""

    name = "generic"

    def __init__(self, site: str | None = None, *args, **kwargs):
        if not site:
            raise ValueError("Pass -a site=<name>, e.g. scrapy crawl generic -a site=quotes")
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
        for key, value in spider._site_custom_settings.items():
            crawler.settings.set(key, value, priority="spider")
        return spider

    @classmethod
    def update_settings(cls, settings):
        CrawlSpider.update_settings(settings)

    def start_requests(self):
        proxy_meta = self.site_config.proxy_meta()
        for url in self.site_config.start_urls:
            yield scrapy.Request(url, callback=self.parse_start_url, meta=dict(proxy_meta))

    def parse_start_url(self, response):
        yield from self.parse_item(response)

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
