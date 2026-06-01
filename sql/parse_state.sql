CREATE TABLE IF NOT EXISTS scraper.parse_state
(
    spider LowCardinality(String),
    watermark DateTime,
    updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (spider);
