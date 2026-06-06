from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from scraper.parse.worker import _get_client, _load_settings_from_env, _parse_datetime


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _row_from_record(record: dict[str, Any], default_spider: str) -> list[Any]:
    fetched_at = record.get("fetched_at")
    if fetched_at:
        ts = _parse_datetime(fetched_at)
    else:
        ts = datetime.now(timezone.utc)
    return [
        ts.replace(tzinfo=None),
        record.get("spider") or default_spider,
        record.get("url") or "",
        int(record.get("http_status") or 0),
        {str(k): str(v) for k, v in (record.get("headers") or {}).items()},
        record.get("body") or "",
        record.get("payload") or {},
    ]


def run_ingest(
    site: str,
    *,
    input_path: str | None = None,
    batch_size: int | None = None,
) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    settings = _load_settings_from_env()
    output_dir = Path(os.getenv("OUTPUT_DIR", "output"))
    path = Path(input_path) if input_path else output_dir / f"{site}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"No JSONL file at {path}. Pass --input to override.")

    effective_batch = batch_size or settings["batch_size"]
    columns = [
        "fetched_at",
        "spider",
        "url",
        "http_status",
        "headers",
        "body",
        "payload",
    ]

    client = _get_client(settings)
    client.command("SET async_insert = 1")
    client.command("SET wait_for_async_insert = 1")

    total = 0
    buffer: list[list[Any]] = []
    for record in _iter_jsonl(path):
        buffer.append(_row_from_record(record, site))
        if len(buffer) >= effective_batch:
            client.insert(settings["raw_table"], buffer, column_names=columns)
            total += len(buffer)
            buffer.clear()

    if buffer:
        client.insert(settings["raw_table"], buffer, column_names=columns)
        total += len(buffer)

    client.close()
    return total
