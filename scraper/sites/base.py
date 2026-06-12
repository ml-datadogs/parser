from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


ParseFn = Callable[[bytes | str, str], list[dict[str, Any]]]


@dataclass(frozen=True)
class LinkRules:
    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()
    restrict_css: tuple[str, ...] = ()


@dataclass(frozen=True)
class SiteConfig:
    name: str
    allowed_domains: tuple[str, ...]
    start_urls: tuple[str, ...]
    link_rules: LinkRules = field(default_factory=LinkRules)
    proxy_zone: str | None = None
    proxy_country: str | None = None
    # Bright Data Web Unlocker zone. When set (and an API token is configured),
    # requests for this site route through the Unlocker API instead of the
    # residential proxy. Read by BrightDataUnlockerMiddleware via the spider.
    unlocker_zone: str | None = None
    download_delay: float | None = None
    concurrent_requests: int | None = None
    concurrent_requests_per_domain: int | None = None
    autothrottle_target_concurrency: float | None = None
    autothrottle_start_delay: float | None = None
    robots_txt_obey: bool = True
    user_agent: str | None = None
    retry_http_codes: tuple[int, ...] | None = None
    retry_times: int | None = None
    default_request_headers: tuple[tuple[str, str], ...] | None = None

    def custom_settings(self) -> dict[str, Any]:
        settings: dict[str, Any] = {}
        if self.download_delay is not None:
            settings["DOWNLOAD_DELAY"] = self.download_delay
        if self.concurrent_requests is not None:
            settings["CONCURRENT_REQUESTS"] = self.concurrent_requests
        if self.concurrent_requests_per_domain is not None:
            settings["CONCURRENT_REQUESTS_PER_DOMAIN"] = (
                self.concurrent_requests_per_domain
            )
        if self.autothrottle_target_concurrency is not None:
            settings["AUTOTHROTTLE_TARGET_CONCURRENCY"] = (
                self.autothrottle_target_concurrency
            )
        if self.autothrottle_start_delay is not None:
            settings["AUTOTHROTTLE_START_DELAY"] = self.autothrottle_start_delay
        if self.user_agent is not None:
            settings["USER_AGENT"] = self.user_agent
        if self.retry_http_codes is not None:
            settings["RETRY_HTTP_CODES"] = list(self.retry_http_codes)
        if self.retry_times is not None:
            settings["RETRY_TIMES"] = self.retry_times
        if self.default_request_headers is not None:
            settings["DEFAULT_REQUEST_HEADERS"] = dict(self.default_request_headers)
        settings["ROBOTSTXT_OBEY"] = self.robots_txt_obey
        return settings

    def proxy_meta(self) -> dict[str, str]:
        meta: dict[str, str] = {}
        if self.proxy_zone:
            meta["bd_zone"] = self.proxy_zone
        if self.proxy_country:
            meta["bd_country"] = self.proxy_country
        return meta


@dataclass(frozen=True)
class SitePackage:
    config: SiteConfig
    parse: ParseFn | None = None
