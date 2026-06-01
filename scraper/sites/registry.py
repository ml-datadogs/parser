from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Iterator

from scraper.sites.base import SiteConfig, SitePackage

_SITES: dict[str, SitePackage] | None = None
_SITES_DIR = Path(__file__).resolve().parent


def _discover_site_packages() -> Iterator[str]:
    for module_info in pkgutil.iter_modules([str(_SITES_DIR)]):
        if module_info.name in {"base", "registry"}:
            continue
        if module_info.ispkg:
            yield module_info.name


def _load_site_package(name: str) -> SitePackage:
    module = importlib.import_module(f"scraper.sites.{name}")
    config: SiteConfig = module.config
    if config.name != name:
        raise ValueError(
            f"Site package {name!r} config.name is {config.name!r}; they must match."
        )
    parse_fn = getattr(module, "parse", None)
    return SitePackage(config=config, parse=parse_fn)


def load_sites() -> dict[str, SitePackage]:
    global _SITES
    if _SITES is not None:
        return _SITES

    sites: dict[str, SitePackage] = {}
    for name in sorted(_discover_site_packages()):
        sites[name] = _load_site_package(name)
    _SITES = sites
    return sites


def get_site(name: str) -> SitePackage:
    sites = load_sites()
    if name not in sites:
        available = ", ".join(sorted(sites)) or "(none)"
        raise KeyError(f"Unknown site {name!r}. Available: {available}")
    return sites[name]


def list_sites() -> list[str]:
    return sorted(load_sites())
