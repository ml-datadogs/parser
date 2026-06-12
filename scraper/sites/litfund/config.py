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
    # litfund cloaks the residential pool with 404s regardless of exit IP, so
    # route through the Bright Data Web Unlocker (anti-bot solved server-side)
    # when BRIGHTDATA_API_TOKEN is set. Falls back to residential otherwise.
    unlocker_zone="litfund_unlocker",
    # litfund cloaks/404s non-browser User-Agents (e.g. the default bot UA),
    # especially from datacenter IPs, so present a real browser UA.
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    # litfund intermittently cloaks a valid auction as 404 depending on the
    # Bright Data exit IP. Treat 404 (and 403) as retryable so the request is
    # rotated onto a fresh IP (see BrightDataProxyMiddleware per-retry session)
    # instead of being silently dropped. A few extra attempts clear most IPs.
    retry_http_codes=(403, 404, 429, 500, 502, 503, 504),
    retry_times=5,
    # Round out the browser fingerprint (UA alone is not always enough): a real
    # Chrome sends these on a top-level navigation. Reduces fingerprint cloaking.
    default_request_headers=(
        (
            "Accept",
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8",
        ),
        ("Accept-Language", "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"),
        ("Upgrade-Insecure-Requests", "1"),
        ("Sec-Fetch-Dest", "document"),
        ("Sec-Fetch-Mode", "navigate"),
        ("Sec-Fetch-Site", "none"),
        ("Sec-Fetch-User", "?1"),
        (
            "sec-ch-ua",
            '"Chromium";v="124", "Google Chrome";v="124", '
            '"Not-A.Brand";v="99"',
        ),
        ("sec-ch-ua-mobile", "?0"),
        ("sec-ch-ua-platform", '"macOS"'),
    ),
)
