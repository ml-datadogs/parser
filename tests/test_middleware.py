from scrapy.http import Request

from scraper.middlewares import BrightDataProxyMiddleware, build_brightdata_proxy_url


def test_build_brightdata_proxy_url_with_country():
    url = build_brightdata_proxy_url(
        customer="cust123",
        zone="residential",
        password="secret",
        country="us",
    )
    assert "brd-customer-cust123-zone-residential-country-us" in url
    assert "secret" in url
    assert url.endswith("@brd.superproxy.io:33335")


def test_middleware_noop_without_credentials():
    middleware = BrightDataProxyMiddleware(customer="", zone="", password="")
    request = Request("https://example.com")
    assert middleware.process_request(request) is None
    assert "proxy" not in request.meta


def test_middleware_sets_proxy_with_credentials():
    middleware = BrightDataProxyMiddleware(
        customer="cust123",
        zone="residential",
        password="secret",
    )
    request = Request("https://example.com")
    middleware.process_request(request)
    assert "proxy" in request.meta
    assert "brd.superproxy.io" in request.meta["proxy"]


def test_middleware_honors_per_request_country():
    middleware = BrightDataProxyMiddleware(
        customer="cust123",
        zone="residential",
        password="secret",
    )
    request = Request("https://example.com", meta={"bd_country": "de"})
    middleware.process_request(request)
    assert "country-de" in request.meta["proxy"]
