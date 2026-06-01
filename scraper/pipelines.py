from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scrapy import Item, Spider
from scrapy.exceptions import NotConfigured

from scraper.items import RawItem


class JsonLinesExportPipeline:
    """Write RawItems to output/<spider>.jsonl for local inspection."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._file = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def open_spider(self, spider: Spider | None = None) -> None:
        output_dir = Path(spider.settings.get("OUTPUT_DIR", "output"))
        output_dir.mkdir(parents=True, exist_ok=True)
        self._path = output_dir / f"{spider.name}.jsonl"
        self._file = self._path.open("a", encoding="utf-8")

    def close_spider(self, spider: Spider | None = None) -> None:
        if self._file is not None:
            self._file.close()

    def process_item(self, item: Item, spider: Spider | None = None):
        if not isinstance(item, RawItem):
            return item
        record = dict(item)
        record["body"] = _decode_body(record.get("body"))
        self._file.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
        return item


class ClickHouseRawPipeline:
    """Buffer RawItems and bulk-insert into ClickHouse raw_items."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        table: str,
        batch_size: int,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.table = table
        self.batch_size = batch_size
        self._buffer: list[dict[str, Any]] = []
        self._client = None

    @classmethod
    def from_crawler(cls, crawler):
        host = crawler.settings.get("CLICKHOUSE_HOST", "")
        if not host:
            raise NotConfigured("CLICKHOUSE_HOST not set; ClickHouse pipeline disabled.")

        return cls(
            host=host,
            port=crawler.settings.getint("CLICKHOUSE_PORT", 8123),
            user=crawler.settings.get("CLICKHOUSE_USER", "default"),
            password=crawler.settings.get("CLICKHOUSE_PASSWORD", ""),
            database=crawler.settings.get("CLICKHOUSE_DATABASE", "scraper"),
            table=crawler.settings.get("CLICKHOUSE_RAW_TABLE", "raw_items"),
            batch_size=crawler.settings.getint("CLICKHOUSE_BATCH_SIZE", 1000),
        )

    def open_spider(self, spider: Spider | None = None) -> None:
        import clickhouse_connect

        self._client = clickhouse_connect.get_client(
            host=self.host,
            port=self.port,
            username=self.user,
            password=self.password,
            database=self.database,
        )
        self._client.command("SET async_insert = 1")
        self._client.command("SET wait_for_async_insert = 1")

    def close_spider(self, spider: Spider | None = None) -> None:
        self._flush()
        if self._client is not None:
            self._client.close()

    def process_item(self, item: Item, spider: Spider | None = None):
        if not isinstance(item, RawItem):
            return item

        spider_name = (spider.name if spider is not None else None) or item.get("spider") or "unknown"
        self._buffer.append(
            {
                "fetched_at": item.get("fetched_at") or datetime.now(timezone.utc),
                "spider": item.get("spider") or spider_name,
                "url": item.get("url") or "",
                "http_status": int(item.get("http_status") or 0),
                "headers": dict(item.get("headers") or {}),
                "body": _decode_body(item.get("body")),
                "payload": item.get("payload") or {},
            }
        )
        if len(self._buffer) >= self.batch_size:
            self._flush()
        return item

    def _flush(self) -> None:
        if not self._buffer or self._client is None:
            return
        self._client.insert(
            self.table,
            self._buffer,
            column_names=[
                "fetched_at",
                "spider",
                "url",
                "http_status",
                "headers",
                "body",
                "payload",
            ],
        )
        self._buffer.clear()


def _decode_body(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return str(body)
