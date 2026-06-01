from pathlib import Path

import pytest
from scrapy.exceptions import NotConfigured

from scraper.items import RawItem
from scraper.pipelines import ClickHouseRawPipeline, JsonLinesExportPipeline


class DummySpider:
    name = "quotes"

    def __init__(self, settings):
        self.settings = settings


def test_clickhouse_pipeline_disabled_without_host():
    with pytest.raises(NotConfigured):
        ClickHouseRawPipeline.from_crawler(
            type(
                "Crawler",
                (),
                {
                    "settings": type(
                        "Settings",
                        (),
                        {
                            "get": lambda self, key, default="": default,
                            "getint": lambda self, key, default=0: default,
                        },
                    )()
                },
            )()
        )


def test_clickhouse_pipeline_buffers_and_flushes(monkeypatch):
    inserted = []

    class FakeClient:
        def command(self, _sql):
            return None

        def insert(self, table, rows, column_names):
            inserted.extend(rows)

        def close(self):
            return None

    monkeypatch.setattr(
        "clickhouse_connect.get_client",
        lambda **kwargs: FakeClient(),
    )

    pipeline = ClickHouseRawPipeline(
        host="localhost",
        port=8123,
        user="default",
        password="",
        database="scraper",
        table="raw_items",
        batch_size=2,
    )
    spider = DummySpider(settings={"OUTPUT_DIR": "output"})
    pipeline.open_spider(spider)

    for idx in range(2):
        pipeline.process_item(
            RawItem(
                spider="quotes",
                url=f"https://example.com/{idx}",
                http_status=200,
                headers={"content-type": "text/html"},
                body=b"<html></html>",
                fetched_at="2026-05-31T12:00:00+00:00",
                payload={},
            ),
            spider,
        )

    assert len(inserted) == 2
    pipeline.close_spider(spider)


def test_jsonlines_pipeline_writes_file(tmp_path):
    pipeline = JsonLinesExportPipeline()
    spider = DummySpider(settings={"OUTPUT_DIR": str(tmp_path)})
    pipeline.open_spider(spider)
    pipeline.process_item(
        RawItem(
            spider="quotes",
            url="https://example.com",
            http_status=200,
            headers={},
            body=b"<html></html>",
            fetched_at="2026-05-31T12:00:00+00:00",
            payload={},
        ),
        spider,
    )
    pipeline.close_spider(spider)
    output_file = tmp_path / "quotes.jsonl"
    assert output_file.exists()
    assert "https://example.com" in output_file.read_text(encoding="utf-8")
