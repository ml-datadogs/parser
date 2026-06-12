-- Litfund crawl metrics: derived views for data-count estimation and crawl
-- health. Read-only over scraper.raw_items (fetched pages) and
-- scraper.parsed_items (structured records); no new writes.
--
-- URL page-type classification mirrors the regexes in
-- scraper/sites/litfund/discover.py and the litfund_auctions spider:
--   lot     -> /auction/<id>/<lot>/
--   catalog -> /auction/<id>/ (optionally ?page=N)
--   other   -> archives / utility pages

-- Data-count estimation: single-row overview of how much we have parsed.
DROP VIEW IF EXISTS scraper.litfund_data_overview;

CREATE VIEW IF NOT EXISTS scraper.litfund_data_overview AS
WITH auctions AS
(
    SELECT
        JSONExtractString(toString(fields), 'auction_id') AS auction_id,
        argMax(JSONExtractString(toString(fields), 'status'), parsed_at) AS status
    FROM scraper.parsed_items
    WHERE spider = 'litfund'
      AND JSONExtractString(toString(fields), 'type') = 'auction'
    GROUP BY auction_id
),
lots AS
(
    SELECT
        JSONExtractString(toString(fields), 'auction_id') AS auction_id,
        uniqExact(JSONExtractString(toString(fields), 'lot_number')) AS lots_parsed
    FROM scraper.parsed_items
    WHERE spider = 'litfund'
      AND JSONExtractString(toString(fields), 'type') = 'item'
    GROUP BY auction_id
),
joined AS
(
    SELECT
        a.auction_id              AS auction_id,
        a.status                  AS status,
        ifNull(l.lots_parsed, 0)  AS lots_parsed
    FROM auctions AS a
    LEFT JOIN lots AS l USING (auction_id)
)
SELECT
    count()                                AS total_auctions,
    countIf(status = 'completed')          AS completed_auctions,
    countIf(status != 'completed')         AS upcoming_auctions,
    sum(lots_parsed)                       AS total_lots,
    round(avg(lots_parsed), 1)             AS avg_lots_per_auction,
    max(lots_parsed)                       AS max_lots_per_auction,
    countIf(lots_parsed > 0)               AS auctions_with_lots,
    countIf(lots_parsed = 0)               AS auctions_without_lots,
    toUInt64(round(avg(lots_parsed) * count())) AS estimated_total_lots,
    (
        SELECT max(parsed_at)
        FROM scraper.parsed_items
        WHERE spider = 'litfund'
    )                                      AS last_parsed_at
FROM joined;

-- Per-auction coverage: spot auctions fetched but with few/zero parsed lots,
-- or auctions carrying HTTP errors. Bridges data-count and health.
DROP VIEW IF EXISTS scraper.litfund_auction_coverage;

CREATE VIEW IF NOT EXISTS scraper.litfund_auction_coverage AS
WITH auctions AS
(
    SELECT
        JSONExtractString(toString(fields), 'auction_id') AS auction_id,
        argMax(JSONExtractString(toString(fields), 'status'), parsed_at)   AS status,
        argMax(JSONExtractString(toString(fields), 'date_iso'), parsed_at) AS date_iso,
        max(parsed_at) AS last_parsed_at
    FROM scraper.parsed_items
    WHERE spider = 'litfund'
      AND JSONExtractString(toString(fields), 'type') = 'auction'
    GROUP BY auction_id
),
lots AS
(
    SELECT
        JSONExtractString(toString(fields), 'auction_id') AS auction_id,
        uniqExact(JSONExtractString(toString(fields), 'lot_number')) AS lots_parsed
    FROM scraper.parsed_items
    WHERE spider = 'litfund'
      AND JSONExtractString(toString(fields), 'type') = 'item'
    GROUP BY auction_id
),
fetches AS
(
    SELECT
        extract(url, '/auction/([0-9]+(?:[.s][0-9]+)?)/') AS auction_id,
        count()                       AS pages_fetched,
        countIf(http_status != 200)   AS http_errors,
        max(fetched_at)               AS last_fetched_at
    FROM scraper.raw_items
    WHERE spider = 'litfund'
      AND match(url, '/auction/[0-9]+(?:[.s][0-9]+)?/')
    GROUP BY auction_id
)
SELECT
    a.auction_id                    AS auction_id,
    a.status                        AS status,
    a.date_iso                      AS date_iso,
    toDate(nullIf(a.date_iso, ''))  AS auction_date,
    ifNull(l.lots_parsed, 0)        AS lots_parsed,
    a.last_parsed_at                AS last_parsed_at,
    ifNull(f.pages_fetched, 0)      AS pages_fetched,
    ifNull(f.http_errors, 0)        AS http_errors,
    f.last_fetched_at               AS last_fetched_at,
    -- A catalog page holds 36 lot cards. Exactly 36 lots from a single fetched
    -- page means pagination was never followed (the rest of the auction is
    -- missing), as opposed to a genuine small auction that has < 36 lots.
    (ifNull(l.lots_parsed, 0) = 36 AND ifNull(f.pages_fetched, 0) <= 1) AS likely_truncated
FROM auctions AS a
LEFT JOIN lots AS l USING (auction_id)
LEFT JOIN fetches AS f USING (auction_id)
ORDER BY auction_date DESC;

-- Crawl health, day by day: fetch volume, error rate, and page-type mix.
DROP VIEW IF EXISTS scraper.litfund_crawl_health_daily;

CREATE VIEW IF NOT EXISTS scraper.litfund_crawl_health_daily AS
WITH classified AS
(
    SELECT
        toDate(fetched_at) AS fetch_date,
        http_status,
        match(url, '/auction/[0-9]+(?:[.s][0-9]+)?/[0-9]+[a-z]?/') AS is_lot,
        match(url, '/auction/[0-9]+(?:[.s][0-9]+)?/(\\?|$)')       AS is_catalog,
        extract(url, '/auction/([0-9]+(?:[.s][0-9]+)?)/')          AS auction_id
    FROM scraper.raw_items
    WHERE spider = 'litfund'
)
SELECT
    fetch_date,
    count()                                       AS pages_fetched,
    countIf(http_status = 200)                    AS ok_200,
    countIf(http_status != 200)                   AS errors,
    round(countIf(http_status != 200) / count(), 4) AS error_rate,
    countIf(is_lot)                               AS lots,
    countIf(is_catalog AND NOT is_lot)            AS catalogs,
    countIf(NOT is_lot AND NOT is_catalog)        AS archive_other,
    uniqExact(nullIf(auction_id, ''))             AS distinct_auctions_touched
FROM classified
GROUP BY fetch_date
ORDER BY fetch_date;

-- Crawl health, lifetime: single-row rollup over all fetched litfund pages.
DROP VIEW IF EXISTS scraper.litfund_crawl_health_overall;

CREATE VIEW IF NOT EXISTS scraper.litfund_crawl_health_overall AS
WITH classified AS
(
    SELECT
        http_status,
        fetched_at,
        match(url, '/auction/[0-9]+(?:[.s][0-9]+)?/[0-9]+[a-z]?/') AS is_lot,
        match(url, '/auction/[0-9]+(?:[.s][0-9]+)?/(\\?|$)')       AS is_catalog
    FROM scraper.raw_items
    WHERE spider = 'litfund'
)
SELECT
    count()                                       AS total_pages,
    countIf(http_status = 200)                    AS ok_200,
    countIf(http_status != 200)                   AS errors,
    round(countIf(http_status != 200) / count(), 4) AS error_rate,
    countIf(is_lot)                               AS lots,
    countIf(is_catalog AND NOT is_lot)            AS catalogs,
    countIf(NOT is_lot AND NOT is_catalog)        AS archive_other,
    min(fetched_at)                               AS first_fetched_at,
    max(fetched_at)                               AS last_fetched_at
FROM classified;
