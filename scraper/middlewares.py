from __future__ import annotations

import base64
import json
import secrets
from urllib.parse import quote

from scrapy import Request


def build_brightdata_proxy_url(
    *,
    customer: str,
    zone: str,
    password: str,
    host: str = "brd.superproxy.io",
    port: int = 33335,
    country: str | None = None,
    session: str | None = None,
) -> str:
    zone_segment = zone
    if country:
        zone_segment = f"{zone_segment}-country-{country.lower()}"
    if session:
        # Bright Data pins an exit IP per ``-session-<id>``. A distinct id yields
        # a distinct IP, which lets a retry rotate off a flagged/cloaked IP.
        zone_segment = f"{zone_segment}-session-{session}"
    username = f"brd-customer-{customer}-zone-{zone_segment}"
    return f"http://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}"


class BrightDataProxyMiddleware:
    """Inject Bright Data super-proxy into every request when configured."""

    def __init__(
        self,
        customer: str = "",
        zone: str = "",
        password: str = "",
        host: str = "brd.superproxy.io",
        port: int = 33335,
        country: str | None = None,
    ) -> None:
        self.customer = customer
        self.zone = zone
        self.password = password
        self.host = host
        self.port = port
        self.country = country

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        return cls(
            customer=settings.get("BRIGHTDATA_CUSTOMER", ""),
            zone=settings.get("BRIGHTDATA_ZONE", ""),
            password=settings.get("BRIGHTDATA_PASSWORD", ""),
            host=settings.get("BRIGHTDATA_HOST", "brd.superproxy.io"),
            port=settings.getint("BRIGHTDATA_PORT", 33335),
            country=settings.get("BRIGHTDATA_COUNTRY") or None,
        )

    def _enabled(self) -> bool:
        return bool(self.customer and self.zone and self.password)

    def _session_for_request(self, request: Request) -> str:
        # A stable per-request base, suffixed with the retry count, so every
        # retry of the same request rotates onto a fresh Bright Data exit IP
        # while distinct requests also get distinct IPs.
        base = request.meta.get("bd_session_base")
        if not base:
            base = secrets.token_hex(4)
            request.meta["bd_session_base"] = base
        retry = request.meta.get("retry_times", 0)
        return f"{base}r{retry}"

    def _proxy_for_request(self, request: Request) -> str | None:
        if not self._enabled():
            return None

        zone = request.meta.get("bd_zone", self.zone)
        country = request.meta.get("bd_country", self.country)
        return build_brightdata_proxy_url(
            customer=self.customer,
            zone=zone,
            password=self.password,
            host=self.host,
            port=self.port,
            country=country,
            session=self._session_for_request(request),
        )

    def process_request(self, request: Request):
        # Web Unlocker requests go to api.brightdata.com and authenticate via a
        # Bearer token, not the residential proxy. Leave them untouched.
        if request.meta.get("_unlocker_wrapped"):
            return None
        # Honor an externally pinned proxy, but always rebuild one we set
        # ourselves so the per-retry session id (and thus the exit IP) rotates.
        if request.meta.get("proxy") and not request.meta.get("_bd_proxy"):
            return None

        proxy_url = self._proxy_for_request(request)
        if not proxy_url:
            return None

        request.meta["proxy"] = proxy_url
        request.meta["_bd_proxy"] = True
        if "@" in proxy_url:
            credentials, _ = proxy_url.split("@", 1)
            encoded = base64.b64encode(
                credentials.replace("http://", "").encode()
            ).decode()
            request.headers[b"Proxy-Authorization"] = f"Basic {encoded}".encode()
        return None


class BrightDataUnlockerMiddleware:
    """Route a site's requests through the Bright Data Web Unlocker API.

    Some sites (e.g. litfund) actively cloak the residential proxy pool with
    404s regardless of which exit IP is used. The Web Unlocker solves anti-bot
    challenges server-side and returns the target page as raw HTML.

    Active only when an API token is configured *and* the spider's site defines
    an ``unlocker_zone``; otherwise this is a no-op and the residential proxy
    middleware handles the request as before.

    The request is rewritten to ``POST api.brightdata.com/request`` with the
    target URL in the JSON body. On the way back, the original target URL is
    restored on the response so link extraction (relative ``?page=N`` links) and
    the ``raw_items`` pipeline record the real URL, not the API endpoint.
    """

    def __init__(
        self,
        api_token: str = "",
        api_url: str = "https://api.brightdata.com/request",
    ) -> None:
        self.api_token = api_token
        self.api_url = api_url

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        return cls(
            api_token=settings.get("BRIGHTDATA_API_TOKEN", ""),
            api_url=settings.get(
                "BRIGHTDATA_API_URL", "https://api.brightdata.com/request"
            ),
        )

    def _zone_for_request(self, request: Request, spider) -> str | None:
        zone = request.meta.get("bd_unlocker_zone")
        if zone:
            return zone
        config = getattr(spider, "site_config", None)
        return getattr(config, "unlocker_zone", None) if config else None

    def process_request(self, request: Request, spider):
        if not self.api_token or request.meta.get("_unlocker_wrapped"):
            return None

        zone = self._zone_for_request(request, spider)
        if not zone:
            return None

        # Only zone/url/format: the Unlocker zone is geo-configured server-side,
        # and passing a "country" override makes the API return an empty body.
        payload = {"zone": zone, "url": request.url, "format": "raw"}

        return request.replace(
            url=self.api_url,
            method="POST",
            body=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
            # The API host is off the site's allowed_domains and dedup would
            # collapse same-body requests, so opt out of both filters here.
            dont_filter=True,
            meta={
                **request.meta,
                "_unlocker_wrapped": True,
                "_unlocker_url": request.url,
            },
        )

    def process_response(self, request: Request, response, spider):
        original = request.meta.get("_unlocker_url")
        if not original:
            return response
        # The API replies with the raw page but its own Content-Type (often not
        # text/html), so Scrapy may build a plain/Text response on which link
        # extraction is a no-op. Restore the real URL and coerce to HtmlResponse
        # so pagination/lot links are followed and raw_items records the target.
        from scrapy.http import HtmlResponse

        return response.replace(cls=HtmlResponse, url=original)
