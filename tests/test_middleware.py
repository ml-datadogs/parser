import gzip
import json
import logging
from types import SimpleNamespace

import pytest
from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse, Request, TextResponse
from scrapy.settings import Settings

from scraper.middlewares import (
    BrightDataProxyMiddleware,
    BrightDataUnlockerMiddleware,
    build_brightdata_proxy_url,
)
from scraper.spiders.generic import DEFAULT_UNLOCKER_CONCURRENCY, GenericSiteSpider


def _spider(unlocker_zone=None, proxy_country=None):
    return SimpleNamespace(
        site_config=SimpleNamespace(
            unlocker_zone=unlocker_zone, proxy_country=proxy_country
        ),
        logger=logging.getLogger("test"),
    )


def _spider_with_crawler(retry_times=2):
    """A spider whose crawler exposes the settings/stats that get_retry_request
    reads when the Unlocker middleware retries a bad 200."""
    spider = _spider()
    spider.crawler = SimpleNamespace(
        settings=Settings({"RETRY_TIMES": retry_times}),
        stats=SimpleNamespace(inc_value=lambda *a, **k: None),
    )
    return spider


# A body large enough to clear the middleware's minimum-size gate (~500 bytes),
# so size-based tests exercise URL restoration rather than the bad-body retry.
_GOOD_BODY = (
    b"<html><head><meta property='og:url' content='x'>"
    + b"<!-- pad -->" * 60
    + b"</head><body>ok</body></html>"
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
        body=_GOOD_BODY,
        encoding="utf-8",
    )
    restored = middleware.process_response(request, response, _spider())
    assert restored.url == original


def test_unlocker_decompresses_gzip_lot_body():
    """The Unlocker sometimes returns a still-gzip-compressed body whose
    Content-Encoding header Scrapy never decoded. It must be inflated before the
    content gate so a real lot page is not dropped as 'missing microdata' just
    because its raw gzip bytes lack the marker."""
    middleware = BrightDataUnlockerMiddleware(api_token="tok")
    original = "https://www.litfund.ru/auction/716/90/"
    request = Request(
        "https://api.brightdata.com/request", meta={"_unlocker_url": original}
    )
    html = (
        b"<html><head><meta property='og:url' content='x'></head><body>"
        b"<span data-lf-microdata='lot-name'>A book</span>"
        + b"<!-- pad -->" * 60
        + b"</body></html>"
    )
    response = HtmlResponse(
        url="https://api.brightdata.com/request",
        body=gzip.compress(html),
        headers={b"Content-Type": b"text/html; charset=UTF-8"},
    )
    result = middleware.process_response(request, response, _spider_with_crawler())
    assert isinstance(result, HtmlResponse)
    assert result.url == original
    assert b"data-lf-microdata" in result.body
    assert b"Content-Encoding" not in result.headers


def test_unlocker_decompresses_via_content_encoding_header():
    """Honor an explicit Content-Encoding: gzip even when callers strip the body
    down (covers servers that set the header but whose payload Scrapy missed)."""
    middleware = BrightDataUnlockerMiddleware(api_token="tok")
    original = "https://www.litfund.ru/auction/716/"
    request = Request(
        "https://api.brightdata.com/request", meta={"_unlocker_url": original}
    )
    html = b"<html><body>" + b"<!-- pad -->" * 80 + b"</body></html>"
    response = HtmlResponse(
        url="https://api.brightdata.com/request",
        body=gzip.compress(html),
        headers={
            b"Content-Type": b"text/html",
            b"Content-Encoding": b"gzip",
        },
    )
    result = middleware.process_response(request, response, _spider_with_crawler())
    assert isinstance(result, HtmlResponse)
    assert result.body == html


def test_unlocker_retries_empty_body_200():
    """A 200 with an empty/truncated body is a transient Unlocker failure: it
    must be retried (re-issued) rather than stored as a hollow page."""
    middleware = BrightDataUnlockerMiddleware(api_token="tok")
    original = "https://www.litfund.ru/auction/716/90/"
    request = Request(
        "https://api.brightdata.com/request", meta={"_unlocker_url": original}
    )
    response = HtmlResponse(
        url="https://api.brightdata.com/request", body=b"", encoding="utf-8"
    )
    result = middleware.process_response(request, response, _spider_with_crawler())
    assert isinstance(result, Request)
    assert result.meta["retry_times"] == 1


def test_unlocker_drops_lot_page_without_microdata_without_retry():
    """A full 200 lot page that still lacks lot microdata after decompression is
    a genuinely cloaked/removed lot. It must be dropped immediately (no retry,
    which would just multiply billed calls); the low-concurrency heal pass
    recovers it instead."""
    middleware = BrightDataUnlockerMiddleware(api_token="tok")
    original = "https://www.litfund.ru/auction/716/90/"
    request = Request(
        "https://api.brightdata.com/request", meta={"_unlocker_url": original}
    )
    body = b"<html><head><meta property='og:url' content='x'></head><body>"
    body += b"<div class='tm-product-card'>other</div>" * 30
    body += b"</body></html>"
    response = HtmlResponse(
        url="https://api.brightdata.com/request", body=body, encoding="utf-8"
    )
    # retry_times=0 (fresh request): a retryable failure WOULD return a Request,
    # so raising here proves the missing-microdata case is not retried.
    with pytest.raises(IgnoreRequest):
        middleware.process_response(request, response, _spider_with_crawler())


def test_unlocker_drops_bad_200_after_retries_exhausted():
    """Once retries are exhausted, a persistently bad 200 (e.g. a genuinely
    removed lot) is dropped via IgnoreRequest so it never lands in raw_items."""
    middleware = BrightDataUnlockerMiddleware(api_token="tok")
    original = "https://www.litfund.ru/auction/716/90/"
    request = Request(
        "https://api.brightdata.com/request",
        meta={"_unlocker_url": original, "retry_times": 5},
    )
    response = HtmlResponse(
        url="https://api.brightdata.com/request", body=b"", encoding="utf-8"
    )
    with pytest.raises(IgnoreRequest):
        middleware.process_response(request, response, _spider_with_crawler())


def test_unlocker_leaves_error_response_uncoerced():
    """A non-2xx Unlocker reply is an API/upstream error, not a page: it must
    keep its status (so RetryMiddleware/HttpError act on it) and not be dressed
    up as a successful HtmlResponse pointing at the target url."""
    middleware = BrightDataUnlockerMiddleware(api_token="tok")
    original = "https://www.litfund.ru/auction/737/"
    request = Request(
        "https://api.brightdata.com/request", meta={"_unlocker_url": original}
    )
    response = TextResponse(
        url="https://api.brightdata.com/request",
        status=503,
        body=b"upstream error",
        encoding="utf-8",
    )
    result = middleware.process_response(request, response, _spider())
    assert result.status == 503
    assert not isinstance(result, HtmlResponse)
    assert result.url == "https://api.brightdata.com/request"


def test_unlocker_settings_drop_404_and_disable_throttle():
    result = GenericSiteSpider._unlocker_settings(Settings())
    assert 404 not in result["RETRY_HTTP_CODES"]
    assert result["RETRY_TIMES"] == 2
    assert result["AUTOTHROTTLE_ENABLED"] is False
    assert result["DOWNLOAD_DELAY"] == 0
    assert result["CONCURRENT_REQUESTS"] == DEFAULT_UNLOCKER_CONCURRENCY
    assert result["CONCURRENT_REQUESTS_PER_DOMAIN"] == DEFAULT_UNLOCKER_CONCURRENCY
    assert result["DOWNLOAD_TIMEOUT"] >= 60


def test_unlocker_settings_concurrency_override():
    settings = Settings({"BRIGHTDATA_UNLOCKER_CONCURRENCY": 256})
    result = GenericSiteSpider._unlocker_settings(settings)
    assert result["CONCURRENT_REQUESTS"] == 256
    assert result["CONCURRENT_REQUESTS_PER_DOMAIN"] == 256


def test_unlocker_active_requires_both_token_and_zone():
    with_zone = _spider(unlocker_zone="litfund_unlocker")
    without_zone = _spider(unlocker_zone=None)

    assert (
        GenericSiteSpider._unlocker_active(
            with_zone, Settings({"BRIGHTDATA_API_TOKEN": "tok"})
        )
        is True
    )
    assert (
        GenericSiteSpider._unlocker_active(
            with_zone, Settings({"BRIGHTDATA_API_TOKEN": ""})
        )
        is False
    )
    assert (
        GenericSiteSpider._unlocker_active(
            without_zone, Settings({"BRIGHTDATA_API_TOKEN": "tok"})
        )
        is False
    )
