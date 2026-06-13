from __future__ import annotations

import base64
import gzip
import json
import re
import secrets
import time
import zlib
from pathlib import Path
from urllib.parse import quote

from scrapy import Request
from scrapy.downloadermiddlewares.retry import get_retry_request
from scrapy.exceptions import IgnoreRequest

# A litfund lot-detail URL: /auction/<id>/<lot>/. Catalog pages (/auction/<id>/)
# legitimately carry no lot microdata, so the content gate below only applies to
# lot-detail responses.
_LOT_URL_RE = re.compile(r"/auction/\d+(?:[.s]\d+)?/\d+[a-z]?/")
# Real litfund pages are tens of KB; anything this small is a truncated/empty
# 200 (observed: 0-byte bodies from transient Web Unlocker hiccups).
_MIN_BODY_BYTES = 500


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


def build_unlocker_request(
    *,
    api_token: str,
    zone: str,
    target_url: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Build the JSON payload and headers for a Bright Data Web Unlocker call.

    Shared by ``BrightDataUnlockerMiddleware`` (Scrapy) and the standalone
    ``requests``-based fetchers (e.g. litfund archive discovery) so both speak
    to the Unlocker identically. Only zone/url/format are sent: the zone is
    geo-configured server-side and passing a "country" override makes the API
    return an empty body.
    """
    payload = {"zone": zone, "url": target_url, "format": "raw"}
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    return payload, headers


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
        debug_dir: str = "",
        debug_max: int = 20,
    ) -> None:
        self.api_token = api_token
        self.api_url = api_url
        self.debug_dir = debug_dir
        self.debug_max = debug_max
        # Number of bad-200 bodies dumped so far this run, to enforce debug_max.
        self._debug_dumped = 0

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        return cls(
            api_token=settings.get("BRIGHTDATA_API_TOKEN", ""),
            api_url=settings.get(
                "BRIGHTDATA_API_URL", "https://api.brightdata.com/request"
            ),
            debug_dir=settings.get("BRIGHTDATA_UNLOCKER_DEBUG_DIR", ""),
            debug_max=settings.getint("BRIGHTDATA_UNLOCKER_DEBUG_MAX", 20),
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

        # robots.txt is a tiny static file with no anti-bot challenge; routing it
        # through the Unlocker only burns billed retries (and the API has been
        # observed to truncate it to a sub-500-byte body that trips the content
        # gate). Scrapy's RobotsTxtMiddleware treats a failed/empty robots fetch
        # as allow-all, so leaving it unwrapped costs nothing.
        if request.url.endswith("/robots.txt"):
            return None

        zone = self._zone_for_request(request, spider)
        if not zone:
            return None

        payload, headers = build_unlocker_request(
            api_token=self.api_token, zone=zone, target_url=request.url
        )

        return request.replace(
            url=self.api_url,
            method="POST",
            body=json.dumps(payload),
            headers=headers,
            # The API host is off the site's allowed_domains and dedup would
            # collapse same-body requests, so opt out of both filters here.
            dont_filter=True,
            meta={
                **request.meta,
                "_unlocker_wrapped": True,
                "_unlocker_url": request.url,
            },
        )

    @staticmethod
    def _decompress_body(body: bytes, encoding: bytes) -> bytes | None:
        """Inflate a still-compressed body, or ``None`` if it isn't/ can't be.

        Selects the codec from the gzip magic bytes (the observed case) or an
        explicit ``Content-Encoding`` header, falling back across the common
        encodings since the Unlocker is inconsistent about which it sends.
        """
        if body[:2] == b"\x1f\x8b" or encoding == b"gzip":
            try:
                return gzip.decompress(body)
            except (OSError, EOFError, zlib.error):
                return None
        if encoding == b"deflate":
            try:
                return zlib.decompress(body)
            except zlib.error:
                try:
                    # Raw DEFLATE (no zlib header), which some servers send.
                    return zlib.decompress(body, -zlib.MAX_WBITS)
                except zlib.error:
                    return None
        if encoding == b"br":
            try:
                import brotli

                return brotli.decompress(body)
            except Exception:
                return None
        return None

    def _maybe_decompress(self, response, original: str, spider):
        """Return ``response`` with its body inflated when the Unlocker handed
        back a still-compressed payload.

        Bright Data's Web Unlocker intermittently returns a body that is still
        gzip-compressed but whose ``Content-Encoding`` header Scrapy's
        ``HttpCompressionMiddleware`` never acted on (the API frequently omits
        it), so raw gzip bytes reach this middleware. Left undecoded they fail
        the content gate below even though the real page is fully intact, which
        previously surfaced as spurious "lot page missing lot microdata" drops.
        """
        body = response.body or b""
        if not body:
            return response
        encoding = response.headers.get(b"Content-Encoding", b"").lower()
        decompressed = self._decompress_body(body, encoding)
        if decompressed is None:
            return response

        headers = response.headers.copy()
        if b"Content-Encoding" in headers:
            del headers[b"Content-Encoding"]
        spider.logger.debug(
            "Web Unlocker body decompressed for %s (%d -> %d bytes).",
            original,
            len(body),
            len(decompressed),
        )
        return response.replace(body=decompressed, headers=headers)

    def _bad_body_reason(self, response, original: str) -> tuple[str, bool] | None:
        """Classify a 200 Unlocker response that is not a usable page.

        Returns ``(reason, retryable)`` or ``None`` when the body is fine.

        - An empty/truncated body is a transient Unlocker hiccup: ``retryable``,
          since re-issuing usually gets the page on the next attempt.
        - A full lot page that lacks lot microdata (after ``_maybe_decompress``
          has inflated any still-compressed body) is a genuinely cloaked or
          removed lot. Retrying within the same run rarely recovers it and just
          multiplies billed calls, so it is NOT retryable: drop it and let a
          low-concurrency heal pass (``-a heal=1``) recover it later.
        """
        body = response.body or b""
        if len(body) < _MIN_BODY_BYTES:
            return f"empty/short body ({len(body)} bytes)", True
        if _LOT_URL_RE.search(original) and b"data-lf-microdata" not in body:
            return "lot page missing lot microdata", False
        return None

    def _capture_bad_body(self, response, original: str, reason: str, spider) -> None:
        """Surface what the Unlocker actually returned for a dropped bad 200.

        Always logs the Content-Type, body length, and a short head snippet so
        the failure mode is visible at WARNING. When a debug dir is configured,
        also dumps the full raw body (capped at ``debug_max`` per run) so a JSON
        error envelope / challenge page / truncated transfer can be inspected.
        """
        body = response.body or b""
        content_type = response.headers.get(b"Content-Type", b"").decode(
            "latin-1", "replace"
        )
        spider.logger.warning(
            "Web Unlocker bad 200 body for %s (%s): content_type=%r len=%d head=%r",
            original,
            reason,
            content_type,
            len(body),
            body[:300],
        )

        if not self.debug_dir or self._debug_dumped >= self.debug_max:
            return
        try:
            dump_dir = Path(self.debug_dir)
            dump_dir.mkdir(parents=True, exist_ok=True)
            safe_url = re.sub(r"[^A-Za-z0-9]+", "_", original).strip("_")[:120]
            safe_reason = re.sub(r"[^A-Za-z0-9]+", "_", reason).strip("_")[:60]
            path = dump_dir / f"{safe_url}__{safe_reason}__{int(time.time() * 1000)}.bin"
            path.write_bytes(body)
            self._debug_dumped += 1
            spider.logger.warning("Web Unlocker bad 200 body dumped to %s", path)
        except OSError as exc:
            spider.logger.warning(
                "Web Unlocker bad 200 body dump failed for %s (%s).", original, exc
            )

    def process_response(self, request: Request, response, spider):
        original = request.meta.get("_unlocker_url")
        if not original:
            return response

        if not 200 <= response.status < 300:
            # A non-2xx is an Unlocker API failure (bad zone, quota, auth) or a
            # genuine upstream error - not a page. Leave it untouched (and at its
            # real status) so RetryMiddleware handles retryable codes and
            # HttpErrorMiddleware drops the rest, instead of dressing the error
            # body up as a successful page and storing it in raw_items.
            spider.logger.warning(
                "Web Unlocker returned HTTP %s for %s", response.status, original
            )
            return response

        # The Unlocker sometimes returns a still-compressed body that Scrapy did
        # not decode; inflate it before the content gate so a real page is not
        # mistaken for a stripped one (its gzip bytes lack the microdata marker).
        response = self._maybe_decompress(response, original, spider)

        # A 200 with no usable content must never be stored as a (hollow) page.
        # Transient empties are retried; a stripped/cloaked lot page is dropped
        # outright (the heal pass recovers it at low concurrency).
        bad = self._bad_body_reason(response, original)
        if bad is not None:
            reason, retryable = bad
            self._capture_bad_body(response, original, reason, spider)
            if retryable:
                retry_req = get_retry_request(
                    request, spider=spider, reason=f"unlocker bad 200: {reason}"
                )
                if retry_req is not None:
                    return retry_req
                spider.logger.warning(
                    "Web Unlocker exhausted retries for %s (%s); dropping.",
                    original,
                    reason,
                )
            else:
                spider.logger.warning(
                    "Web Unlocker bad 200 for %s (%s); dropping "
                    "(run -a heal=1 at low concurrency to recover).",
                    original,
                    reason,
                )
            raise IgnoreRequest(f"Web Unlocker bad 200 for {original}: {reason}")

        # The API replies with the raw page but its own Content-Type (often not
        # text/html), so Scrapy may build a plain/Text response on which link
        # extraction is a no-op. Restore the real URL and coerce to HtmlResponse
        # so pagination/lot links are followed and raw_items records the target.
        from scrapy.http import HtmlResponse

        return response.replace(cls=HtmlResponse, url=original)
