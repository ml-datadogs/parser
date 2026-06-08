CREATE TABLE IF NOT EXISTS scraper.parsed_items
(
    spider LowCardinality(String),
    url String,
    source_fetched_at DateTime,
    parsed_at DateTime DEFAULT now(),
    fields JSON,
    dedup_key UInt64 MATERIALIZED cityHash64(toString(fields))
)
ENGINE = ReplacingMergeTree(parsed_at)
PARTITION BY toStartOfMonth(source_fetched_at)
ORDER BY (spider, url, dedup_key);
