from __future__ import annotations

from datetime import datetime, timezone

import scrapy

from scraper.items import RawItem
from scraper.sites.base import SiteConfig


class BaseSpider(scrapy.Spider):
    """Apply site config and emit RawItem for every fetched response."""

    site_name: str | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, "site_config"):
            self.site_config = None

    @classmethod
    def update_settings(cls, settings):
        super().update_settings(settings)
        site_name = getattr(cls, "site_name", None)
        if site_name:
            from scraper.sites.registry import get_site

            site = get_site(site_name)
            settings.setdict(site.config.custom_settings(), priority="spider")

    def start_requests(self):
        if self.site_config is None:
            raise RuntimeError(f"{self.name} spider requires site_config to be set.")
        proxy_meta = self.site_config.proxy_meta()
        for url in self.site_config.start_urls:
            yield scrapy.Request(url, callback=self.parse, meta=dict(proxy_meta))

    def parse(self, response, **kwargs):
        yield self.raw_item_from_response(response)

    def raw_item_from_response(self, response) -> RawItem:
        headers = {
            key.decode() if isinstance(key, bytes) else str(key): (
                value[0].decode() if isinstance(value[0], bytes) else str(value[0])
            )
            for key, value in response.headers.items()
        }
        return RawItem(
            spider=self.name,
            url=response.url,
            http_status=response.status,
            headers=headers,
            body=response.body,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            payload={},
        )
