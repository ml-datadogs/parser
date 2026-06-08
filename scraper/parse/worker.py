from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from scraper.sites.registry import get_site

logger = logging.getLogger("scraper.parse")


def _get_client(settings: dict[str, Any]):
    import clickhouse_connect

    return clickhouse_connect.get_client(
        host=settings["host"],
        port=settings["port"],
        username=settings["user"],
        password=settings["password"],
        database=settings["database"],
    )


def _load_settings_from_env() -> dict[str, Any]:
    import os

    from dotenv import load_dotenv

    load_dotenv()
    host = os.getenv("CLICKHOUSE_HOST", "")
    if not host:
        raise RuntimeError("CLICKHOUSE_HOST is required for the parse worker.")
    return {
        "host": host,
        "port": int(os.getenv("CLICKHOUSE_PORT", "8123")),
        "user": os.getenv("CLICKHOUSE_USER", "default"),
        "password": os.getenv("CLICKHOUSE_PASSWORD", ""),
        "database": os.getenv("CLICKHOUSE_DATABASE", "scraper"),
        "raw_table": os.getenv("CLICKHOUSE_RAW_TABLE", "raw_items"),
        "parsed_table": os.getenv("CLICKHOUSE_PARSED_TABLE", "parsed_items"),
        "state_table": os.getenv("CLICKHOUSE_STATE_TABLE", "parse_state"),
        "batch_size": int(os.getenv("PARSE_BATCH_SIZE", "1000")),
    }


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Unsupported datetime value: {value!r}")


def get_watermark(client, state_table: str, spider: str) -> datetime:
    result = client.query(
        f"""
        SELECT argMax(watermark, updated_at) AS watermark
        FROM {state_table}
        WHERE spider = {{spider:String}}
        """,
        parameters={"spider": spider},
    )
    if result.result_rows and result.result_rows[0][0] is not None:
        return _parse_datetime(result.result_rows[0][0])
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def set_watermark(client, state_table: str, spider: str, watermark: datetime) -> None:
    client.insert(
        state_table,
        [
            [
                spider,
                watermark.replace(tzinfo=None),
                datetime.now(timezone.utc).replace(tzinfo=None),
            ]
        ],
        column_names=["spider", "watermark", "updated_at"],
    )


def fetch_raw_batch(
    client,
    raw_table: str,
    spider: str,
    watermark: datetime,
    batch_size: int,
) -> list[dict[str, Any]]:
    result = client.query(
        f"""
        SELECT url, body, fetched_at
        FROM {raw_table}
        WHERE spider = {{spider:String}} AND fetched_at > {{watermark:DateTime}}
        ORDER BY fetched_at
        LIMIT {{limit:UInt32}}
        """,
        parameters={
            "spider": spider,
            "watermark": watermark.replace(tzinfo=None),
            "limit": batch_size,
        },
    )
    rows: list[dict[str, Any]] = []
    for url, body, fetched_at in result.result_rows:
        rows.append(
            {"url": url, "body": body, "fetched_at": _parse_datetime(fetched_at)}
        )
    return rows


def insert_parsed_rows(
    client,
    parsed_table: str,
    spider: str,
    url: str,
    source_fetched_at: datetime,
    records: list[dict[str, Any]],
) -> None:
    if not records:
        return
    rows = [
        [
            spider,
            url,
            source_fetched_at.replace(tzinfo=None),
            datetime.now(timezone.utc).replace(tzinfo=None),
            record,
        ]
        for record in records
    ]
    client.insert(
        parsed_table,
        rows,
        column_names=["spider", "url", "source_fetched_at", "parsed_at", "fields"],
    )


def run_parse_worker(
    site: str,
    *,
    reset: bool = False,
    since: datetime | None = None,
    batch_size: int | None = None,
) -> int:
    settings = _load_settings_from_env()
    site_pkg = get_site(site)
    if site_pkg.parse is None:
        raise RuntimeError(f"Site {site!r} has no parser defined.")

    client = _get_client(settings)
    client.command("SET async_insert = 1")
    client.command("SET wait_for_async_insert = 1")

    if reset or since is not None:
        watermark = since or datetime(1970, 1, 1, tzinfo=timezone.utc)
    else:
        watermark = get_watermark(client, settings["state_table"], site)

    effective_batch = batch_size or settings["batch_size"]
    total_parsed = 0
    total_rows = 0
    batch_no = 0

    logger.info(
        "parse start: site=%r watermark=%s batch_size=%d reset=%s",
        site,
        watermark.isoformat(),
        effective_batch,
        reset,
    )

    while True:
        batch = fetch_raw_batch(
            client,
            settings["raw_table"],
            site,
            watermark,
            effective_batch,
        )
        if not batch:
            logger.debug("no more rows after watermark=%s", watermark.isoformat())
            break

        batch_no += 1
        batch_parsed = 0
        max_fetched_at = watermark
        for row in batch:
            records = site_pkg.parse(row["body"], row["url"])
            insert_parsed_rows(
                client,
                settings["parsed_table"],
                site,
                row["url"],
                row["fetched_at"],
                records,
            )
            batch_parsed += len(records)
            logger.debug("parsed %d records from %s", len(records), row["url"])
            if row["fetched_at"] > max_fetched_at:
                max_fetched_at = row["fetched_at"]

        total_parsed += batch_parsed
        total_rows += len(batch)
        watermark = max_fetched_at
        set_watermark(client, settings["state_table"], site, watermark)
        logger.info(
            "batch %d: rows=%d parsed=%d watermark=%s (totals rows=%d parsed=%d)",
            batch_no,
            len(batch),
            batch_parsed,
            watermark.isoformat(),
            total_rows,
            total_parsed,
        )

        if len(batch) < effective_batch:
            break

    client.close()
    logger.info(
        "parse done: site=%r rows=%d records=%d", site, total_rows, total_parsed
    )
    return total_parsed
