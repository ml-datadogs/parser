CREATE DATABASE IF NOT EXISTS scraper;

CREATE TABLE IF NOT EXISTS scraper.raw_items
(
    fetched_at DateTime DEFAULT now(),
    spider LowCardinality(String),
    url String,
    http_status UInt16,
    headers Map(String, String),
    body String,
    payload JSON DEFAULT '{}'
)
ENGINE = MergeTree()
PARTITION BY toStartOfMonth(fetched_at)
ORDER BY (spider, fetched_at)
TTL fetched_at + INTERVAL 6 MONTH DELETE;
