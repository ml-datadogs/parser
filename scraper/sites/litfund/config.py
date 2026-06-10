from scraper.sites.base import LinkRules, SiteConfig

config = SiteConfig(
    name="litfund",
    allowed_domains=("litfund.ru", "www.litfund.ru"),
    # Start from the most recent auction; CrawlSpider follows pagination, lots,
    # and links to older auctions from here. Use "https://www.litfund.ru/auction/"
    # to crawl the whole archive instead.
    start_urls=("https://www.litfund.ru/auction/757/",),
    link_rules=LinkRules(
        # Auction ids are numeric with an optional session suffix (757, 671s1,
        # 739.2). This avoids following utility pages like /auction/rules/.
        allow=(
            r"/auction/\d+(?:[.s]\d+)?/$",
            r"/auction/\d+(?:[.s]\d+)?/\d+/$",
            r"/auction/\d+(?:[.s]\d+)?/\?page=\d+",
        ),
    ),
    # Throughput is bounded by this single domain, so the per-domain limit is
    # the real politeness cap; autothrottle backs off if litfund slows down.
    download_delay=0.25,
    concurrent_requests_per_domain=8,
    autothrottle_target_concurrency=8.0,
    autothrottle_start_delay=0.25,
    proxy_country="ru",
    # litfund cloaks/404s non-browser User-Agents (e.g. the default bot UA),
    # especially from datacenter IPs, so present a real browser UA.
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
)
