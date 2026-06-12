from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from scraper.sites.registry import get_site

logger = logging.getLogger("scraper.parse")

INSERT_MAX_ATTEMPTS = 3
INSERT_BACKOFF_BASE_SECONDS = 1.0


def _get_client(settings: dict[str, Any]):
    import clickhouse_connect

    return clickhouse_connect.get_client(
        host=settings["host"],
        port=settings["port"],
        username=settings["user"],
        password=settings["password"],
        database=settings["database"],
        connect_timeout=settings.get("connect_timeout", 10),
        send_receive_timeout=settings.get("send_receive_timeout", 300),
        query_retries=settings.get("query_retries", 3),
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
        "connect_timeout": int(os.getenv("CLICKHOUSE_CONNECT_TIMEOUT", "10")),
        "send_receive_timeout": int(
            os.getenv("CLICKHOUSE_SEND_RECEIVE_TIMEOUT", "300")
        ),
        "query_retries": int(os.getenv("CLICKHOUSE_QUERY_RETRIES", "3")),
    }


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Unsupported datetime value: {value!r}")


def _ensure_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime.

    ClickHouse columns are UTC and the driver returns naive datetimes for them.
    Passing naive datetimes back (as values or query params) makes the driver
    assume the local timezone, silently shifting every timestamp. Keeping values
    tz-aware UTC avoids that and, for the parse watermark, prevents an infinite
    reprocessing loop when the worker's machine is not on UTC.
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


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
                _ensure_utc(watermark),
                datetime.now(timezone.utc),
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
        WHERE spider = {{spider:String}} AND fetched_at > {{watermark:DateTime('UTC')}}
        ORDER BY fetched_at
        LIMIT {{limit:UInt32}}
        """,
        parameters={
            "spider": spider,
            "watermark": _ensure_utc(watermark),
            "limit": batch_size,
        },
    )
    rows: list[dict[str, Any]] = []
    for url, body, fetched_at in result.result_rows:
        rows.append(
            {"url": url, "body": body, "fetched_at": _parse_datetime(fetched_at)}
        )
    return rows


PARSED_COLUMNS = ["spider", "url", "source_fetched_at", "parsed_at", "fields"]


def build_parsed_rows(
    spider: str,
    url: str,
    source_fetched_at: datetime,
    records: list[dict[str, Any]],
) -> list[list[Any]]:
    parsed_at = datetime.now(timezone.utc)
    return [
        [
            spider,
            url,
            _ensure_utc(source_fetched_at),
            parsed_at,
            record,
        ]
        for record in records
    ]


def insert_parsed_rows(
    client,
    settings: dict[str, Any],
    rows: list[list[Any]],
):
    """Insert parsed rows in a single request, retrying transient drops.

    Returns the (possibly recreated) client. The connection is rebuilt between
    attempts because a connection that hit an SSL EOF can be left in a stale
    state. On final failure the underlying error is re-raised so the caller can
    avoid advancing the watermark, keeping the run resumable.
    """
    from clickhouse_connect.driver.exceptions import OperationalError

    if not rows:
        return client

    parsed_table = settings["parsed_table"]
    last_exc: Exception | None = None
    for attempt in range(1, INSERT_MAX_ATTEMPTS + 1):
        try:
            client.insert(parsed_table, rows, column_names=PARSED_COLUMNS)
            return client
        except OperationalError as exc:
            last_exc = exc
            logger.warning(
                "insert attempt %d/%d failed: %s",
                attempt,
                INSERT_MAX_ATTEMPTS,
                exc,
            )
            if attempt == INSERT_MAX_ATTEMPTS:
                break
            try:
                client.close()
            except Exception:
                logger.debug("error closing stale client", exc_info=True)
            time.sleep(INSERT_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
            client = _get_client(settings)

    assert last_exc is not None
    raise last_exc


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
        pending_rows: list[list[Any]] = []
        for row in batch:
            records = site_pkg.parse(row["body"], row["url"])
            pending_rows.extend(
                build_parsed_rows(site, row["url"], row["fetched_at"], records)
            )
            batch_parsed += len(records)
            logger.debug("parsed %d records from %s", len(records), row["url"])
            if row["fetched_at"] > max_fetched_at:
                max_fetched_at = row["fetched_at"]

        client = insert_parsed_rows(client, settings, pending_rows)

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
