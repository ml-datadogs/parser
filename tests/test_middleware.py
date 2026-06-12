import json
from types import SimpleNamespace

from scrapy.http import HtmlResponse, Request

from scraper.middlewares import (
    BrightDataProxyMiddleware,
    BrightDataUnlockerMiddleware,
    build_brightdata_proxy_url,
)


def _spider(unlocker_zone=None, proxy_country=None):
    return SimpleNamespace(
        site_config=SimpleNamespace(
            unlocker_zone=unlocker_zone, proxy_country=proxy_country
        )
    )


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


def test_build_brightdata_proxy_url_with_session():
    url = build_brightdata_proxy_url(
        customer="cust123",
        zone="residential",
        password="secret",
        country="ru",
        session="abcd1234r0",
    )
    assert "zone-residential-country-ru-session-abcd1234r0" in url


def test_middleware_rotates_exit_ip_on_retry():
    """A cloaked 404 is retried; each retry must use a new Bright Data session
    id (and thus a fresh exit IP) instead of the previous, flagged one."""
    middleware = BrightDataProxyMiddleware(
        customer="cust123",
        zone="residential",
        password="secret",
    )
    request = Request("https://example.com")
    middleware.process_request(request)
    first = request.meta["proxy"]

    # Simulate RetryMiddleware re-dispatching the request.
    request.meta["retry_times"] = 1
    middleware.process_request(request)
    second = request.meta["proxy"]

    assert "-session-" in first
    assert "-session-" in second
    assert first != second


def test_middleware_respects_externally_pinned_proxy():
    middleware = BrightDataProxyMiddleware(
        customer="cust123",
        zone="residential",
        password="secret",
    )
    request = Request("https://example.com", meta={"proxy": "http://pinned:8080"})
    middleware.process_request(request)
    assert request.meta["proxy"] == "http://pinned:8080"


def test_proxy_middleware_skips_unlocker_requests():
    middleware = BrightDataProxyMiddleware(
        customer="cust123",
        zone="residential",
        password="secret",
    )
    request = Request(
        "https://api.brightdata.com/request", meta={"_unlocker_wrapped": True}
    )
    middleware.process_request(request)
    assert "proxy" not in request.meta


def test_unlocker_noop_without_token():
    middleware = BrightDataUnlockerMiddleware(api_token="")
    request = Request("https://www.litfund.ru/auction/737/")
    assert (
        middleware.process_request(request, _spider(unlocker_zone="litfund_unlocker"))
        is None
    )


def test_unlocker_noop_without_zone():
    middleware = BrightDataUnlockerMiddleware(api_token="tok")
    request = Request("https://www.litfund.ru/auction/737/")
    assert middleware.process_request(request, _spider(unlocker_zone=None)) is None


def test_unlocker_wraps_request_to_api():
    middleware = BrightDataUnlockerMiddleware(
        api_token="tok", api_url="https://api.brightdata.com/request"
    )
    request = Request(
        "https://www.litfund.ru/auction/737/", callback=None, meta={"depth": 2}
    )
    wrapped = middleware.process_request(
        request, _spider(unlocker_zone="litfund_unlocker", proxy_country="ru")
    )

    assert wrapped is not None
    assert wrapped.url == "https://api.brightdata.com/request"
    assert wrapped.method == "POST"
    assert wrapped.dont_filter is True
    assert wrapped.headers.get(b"Authorization") == b"Bearer tok"
    body = json.loads(wrapped.body)
    # No "country": the zone is geo-configured server-side and a country
    # override makes the Unlocker API return an empty body.
    assert body == {
        "zone": "litfund_unlocker",
        "url": "https://www.litfund.ru/auction/737/",
        "format": "raw",
    }
    assert wrapped.meta["_unlocker_wrapped"] is True
    assert wrapped.meta["_unlocker_url"] == "https://www.litfund.ru/auction/737/"
    # Preserves unrelated meta so depth/retry bookkeeping survives.
    assert wrapped.meta["depth"] == 2


def test_unlocker_does_not_double_wrap():
    middleware = BrightDataUnlockerMiddleware(api_token="tok")
    request = Request(
        "https://api.brightdata.com/request", meta={"_unlocker_wrapped": True}
    )
    assert (
        middleware.process_request(request, _spider(unlocker_zone="litfund_unlocker"))
        is None
    )


def test_unlocker_restores_original_url_on_response():
    middleware = BrightDataUnlockerMiddleware(api_token="tok")
    original = "https://www.litfund.ru/auction/737/"
    request = Request(
        "https://api.brightdata.com/request", meta={"_unlocker_url": original}
    )
    response = HtmlResponse(
        url="https://api.brightdata.com/request",
        body=b"<html><meta property='og:url' content='x'></html>",
        encoding="utf-8",
    )
    restored = middleware.process_response(request, response, _spider())
    assert restored.url == original
