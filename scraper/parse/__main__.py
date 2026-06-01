from __future__ import annotations

import argparse
from datetime import datetime

from scraper.parse.worker import run_parse_worker
from scraper.sites.registry import list_sites


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse raw ClickHouse rows into parsed_items.")
    parser.add_argument("--site", required=True, help=f"Site name. Available: {', '.join(list_sites())}")
    parser.add_argument("--reset", action="store_true", help="Reprocess from the beginning.")
    parser.add_argument("--since", help="Reprocess rows fetched after this ISO datetime.")
    parser.add_argument("--batch-size", type=int, help="Rows to read per batch.")
    args = parser.parse_args()

    since = datetime.fromisoformat(args.since) if args.since else None
    total = run_parse_worker(
        args.site,
        reset=args.reset,
        since=since,
        batch_size=args.batch_size,
    )
    print(f"Parsed {total} records for site={args.site!r}.")


if __name__ == "__main__":
    main()
