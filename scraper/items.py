import scrapy


class RawItem(scrapy.Item):
    """Generic raw-first item emitted by every spider."""

    spider = scrapy.Field()
    url = scrapy.Field()
    http_status = scrapy.Field()
    headers = scrapy.Field()
    body = scrapy.Field()
    fetched_at = scrapy.Field()
    payload = scrapy.Field()
