from __future__ import annotations

import base64
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
) -> str:
    zone_segment = zone
    if country:
        zone_segment = f"{zone}-country-{country.lower()}"
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
        )

    def process_request(self, request: Request):
        if request.meta.get("proxy"):
            return None

        proxy_url = self._proxy_for_request(request)
        if not proxy_url:
            return None

        request.meta["proxy"] = proxy_url
        if "@" in proxy_url:
            credentials, _ = proxy_url.split("@", 1)
            encoded = base64.b64encode(
                credentials.replace("http://", "").encode()
            ).decode()
            request.headers[b"Proxy-Authorization"] = f"Basic {encoded}".encode()
        return None
