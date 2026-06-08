from __future__ import annotations

import argparse
import logging
import os

from scraper.ingest.worker import run_ingest
from scraper.sites.registry import list_sites


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load exported JSONL raw pages into ClickHouse raw_items."
    )
    parser.add_argument(
        "--site", required=True, help=f"Site name. Available: {', '.join(list_sites())}"
    )
    parser.add_argument(
        "--input",
        help="Path to the JSONL file. Defaults to output/<site>.jsonl. "
        "Crawls via the generic spider write output/generic.jsonl, so pass that here.",
    )
    parser.add_argument("--batch-size", type=int, help="Rows to insert per batch.")
    args = parser.parse_args()

    _configure_logging()
    total = run_ingest(args.site, input_path=args.input, batch_size=args.batch_size)
    print(f"Loaded {total} raw rows into ClickHouse for site={args.site!r}.")


if __name__ == "__main__":
    main()
