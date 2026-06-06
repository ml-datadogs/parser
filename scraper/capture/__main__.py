from __future__ import annotations

import argparse
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from scraper.middlewares import build_brightdata_proxy_url
from scraper.sites.registry import get_site, list_sites


def _build_proxy_url(site_name: str) -> str | None:
    load_dotenv()
    customer = os.getenv("BRIGHTDATA_CUSTOMER", "")
    zone = os.getenv("BRIGHTDATA_ZONE", "")
    password = os.getenv("BRIGHTDATA_PASSWORD", "")
    if not (customer and zone and password):
        return None

    site = get_site(site_name)
    return build_brightdata_proxy_url(
        customer=customer,
        zone=site.config.proxy_zone or zone,
        password=password,
        host=os.getenv("BRIGHTDATA_HOST", "brd.superproxy.io"),
        port=int(os.getenv("BRIGHTDATA_PORT", "33335")),
        country=site.config.proxy_country or os.getenv("BRIGHTDATA_COUNTRY") or None,
    )


def capture_fixture(site_name: str, url: str, name: str = "listing") -> Path:
    site = get_site(site_name)
    fixtures_dir = (
        Path(__file__).resolve().parents[1] / "sites" / site_name / "fixtures"
    )
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    output_path = fixtures_dir / f"{name}.html"

    proxies = None
    proxy_url = _build_proxy_url(site_name)
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    verify_ssl = os.getenv("BRIGHTDATA_VERIFY_SSL", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    response = requests.get(url, proxies=proxies, timeout=60, verify=verify_ssl)
    response.raise_for_status()
    output_path.write_bytes(response.content)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a live page and save it as a site fixture."
    )
    parser.add_argument(
        "--site", required=True, help=f"Site name. Available: {', '.join(list_sites())}"
    )
    parser.add_argument("--url", required=True, help="Page URL to fetch.")
    parser.add_argument(
        "--name", default="listing", help="Fixture filename without extension."
    )
    args = parser.parse_args()

    output_path = capture_fixture(args.site, args.url, args.name)
    print(f"Saved fixture to {output_path}")


if __name__ == "__main__":
    main()
