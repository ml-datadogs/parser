from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scrapy import Item
from scrapy.crawler import Crawler
from scrapy.exceptions import NotConfigured

from scraper.items import RawItem

logger = logging.getLogger(__name__)


class JsonLinesExportPipeline:
    """Write RawItems to output/<spider>.jsonl for local inspection."""

    def __init__(self, crawler: Crawler) -> None:
        self.crawler = crawler
        self._file = None

    @classmethod
    def from_crawler(cls, crawler: Crawler):
        return cls(crawler)

    def open_spider(self) -> None:
        spider = self.crawler.spider
        output_dir = Path(self.crawler.settings.get("OUTPUT_DIR", "output"))
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{spider.name}.jsonl"
        self._file = path.open("a", encoding="utf-8")

    def close_spider(self) -> None:
        if self._file is not None:
            self._file.close()

    def process_item(self, item: Item):
        if not isinstance(item, RawItem):
            return item
        record = dict(item)
        record["body"] = _decode_body(record.get("body"))
        self._file.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
        return item


class ClickHouseRawPipeline:
    """Buffer RawItems and bulk-insert into ClickHouse raw_items."""

    COLUMNS = [
        "fetched_at",
        "spider",
        "url",
        "http_status",
        "headers",
        "body",
        "payload",
    ]

    def __init__(
        self,
        crawler: Crawler,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        table: str,
        batch_size: int,
    ) -> None:
        self.crawler = crawler
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.table = table
        self.batch_size = batch_size
        self._buffer: list[list[Any]] = []
        self._client = None

    @classmethod
    def from_crawler(cls, crawler: Crawler):
        host = crawler.settings.get("CLICKHOUSE_HOST", "")
        if not host:
            raise NotConfigured(
                "CLICKHOUSE_HOST not set; ClickHouse pipeline disabled."
            )

        return cls(
            crawler=crawler,
            host=host,
            port=crawler.settings.getint("CLICKHOUSE_PORT", 8123),
            user=crawler.settings.get("CLICKHOUSE_USER", "default"),
            password=crawler.settings.get("CLICKHOUSE_PASSWORD", ""),
            database=crawler.settings.get("CLICKHOUSE_DATABASE", "scraper"),
            table=crawler.settings.get("CLICKHOUSE_RAW_TABLE", "raw_items"),
            batch_size=crawler.settings.getint("CLICKHOUSE_BATCH_SIZE", 1000),
        )

    def open_spider(self) -> None:
        import clickhouse_connect

        # autogenerate_session_id=False -> stateless requests. A shared session
        # is locked by the server while one request is in flight, and Scrapy
        # processes items concurrently, so concurrent buffer flushes on a shared
        # session raise SESSION_IS_LOCKED (code 373). async_insert is passed per
        # insert instead of via a stateful ``SET`` (which would need a session).
        self._client = clickhouse_connect.get_client(
            host=self.host,
            port=self.port,
            username=self.user,
            password=self.password,
            database=self.database,
            autogenerate_session_id=False,
        )

    def close_spider(self) -> None:
        self._flush()
        if self._client is not None:
            self._client.close()

    def process_item(self, item: Item):
        if not isinstance(item, RawItem):
            return item

        spider = self.crawler.spider
        spider_name = getattr(spider, "name", None) or item.get("spider") or "unknown"
        self._buffer.append(
            [
                _to_naive_utc(item.get("fetched_at")),
                item.get("spider") or spider_name,
                item.get("url") or "",
                int(item.get("http_status") or 0),
                {str(k): str(v) for k, v in (item.get("headers") or {}).items()},
                _decode_body(item.get("body")),
                item.get("payload") or {},
            ]
        )
        if len(self._buffer) >= self.batch_size:
            self._flush()
        return item

    def _flush(self) -> None:
        if not self._buffer or self._client is None:
            return
        try:
            self._client.insert(
                self.table,
                self._buffer,
                column_names=self.COLUMNS,
                settings={"async_insert": 1, "wait_for_async_insert": 1},
            )
        except Exception as exc:
            # Keep the buffer and retry on the next flush instead of letting the
            # exception bubble to Scrapy's item-error logger, which would dump
            # the whole RawItem (including the full page body) for every row.
            logger.warning(
                "ClickHouse insert of %d row(s) failed (%s); retrying on next flush.",
                len(self._buffer),
                exc,
            )
            return
        self._buffer.clear()


def _to_naive_utc(value: Any) -> datetime:
    """Coerce a datetime or ISO string into a naive UTC datetime for ClickHouse."""
    if isinstance(value, str) and value:
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            value = None
    if not isinstance(value, datetime):
        value = datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _decode_body(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return str(body)
