from __future__ import annotations

import scrapy

from scraper.sites.registry import get_site
from scraper.spiders.base import BaseSpider


class ExampleCustomSpider(BaseSpider):
    """Example hand-written spider for sites that do not fit the generic config."""

    name = "example_custom"
    site_name = "quotes"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.site_config = get_site("quotes").config

    def parse(self, response, **kwargs):
        yield self.raw_item_from_response(response)
        for href in response.css("li.next a::attr(href)").getall():
            yield response.follow(href, callback=self.parse)
