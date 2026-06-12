DROP VIEW IF EXISTS scraper.litfund_items;

CREATE VIEW IF NOT EXISTS scraper.litfund_items AS
WITH extracted AS
(
    SELECT
        parsed_at,
        source_fetched_at,
        JSONExtractString(toString(fields), 'auction_id')  AS auction_id,
        JSONExtractString(toString(fields), 'lot_number')  AS lot_number,
        JSONExtractString(toString(fields), 'lot_index')   AS lot_index,
        JSONExtractString(toString(fields), 'title')       AS title,
        JSONExtractString(toString(fields), 'description') AS description,
        JSONExtractString(toString(fields), 'start_price') AS start_price,
        JSONExtractString(toString(fields), 'leading_bid') AS leading_bid,
        JSONExtractString(toString(fields), 'final_price') AS final_price,
        JSONExtractBool(toString(fields), 'reserve_not_met') AS reserve_not_met,
        JSONExtractString(toString(fields), 'views')       AS views,
        JSONExtract(toString(fields), 'images', 'Array(String)') AS images,
        JSONExtractString(toString(fields), 'source_url')  AS source_url
    FROM scraper.parsed_items
    WHERE spider = 'litfund'
      AND JSONExtractString(toString(fields), 'type') = 'item'
),
auctions AS
(
    SELECT
        JSONExtractString(toString(fields), 'auction_id') AS auction_id,
        argMax(JSONExtractString(toString(fields), 'date_iso'), parsed_at) AS date_iso
    FROM scraper.parsed_items
    WHERE spider = 'litfund'
      AND JSONExtractString(toString(fields), 'type') = 'auction'
    GROUP BY auction_id
),
aggregated AS
(
    SELECT
        auction_id,
        lot_number,
        argMaxIf(lot_index,   parsed_at, lot_index != '')        AS lot_index,
        argMaxIf(title,       parsed_at, title != '')            AS title,
        argMaxIf(description, parsed_at, description != '')       AS description,
        argMaxIf(start_price, parsed_at, start_price != '')      AS start_price_str,
        argMaxIf(leading_bid, parsed_at, leading_bid != '')      AS leading_bid_str,
        argMaxIf(final_price, parsed_at, final_price != '')      AS final_price_str,
        argMaxIf(reserve_not_met, parsed_at, final_price != '')  AS reserve_not_met,
        argMaxIf(views,       parsed_at, views != '')            AS views_str,
        argMaxIf(images,      parsed_at, length(images) > 0)     AS images,
        argMaxIf(source_url,  parsed_at, source_url != '')       AS source_url,
        max(parsed_at)         AS last_parsed_at,
        max(source_fetched_at) AS last_source_fetched_at
    FROM extracted
    GROUP BY auction_id, lot_number
)
SELECT
    auction_id,
    lot_number,
    lot_index,
    title,
    description,
    toUInt64OrNull(replaceRegexpAll(start_price_str, '[^0-9]', '')) AS start_price,
    toUInt64OrNull(replaceRegexpAll(leading_bid_str, '[^0-9]', '')) AS leading_bid,
    toUInt64OrNull(replaceRegexpAll(final_price_str, '[^0-9]', '')) AS final_price,
    reserve_not_met,
    toUInt64OrNull(replaceRegexpAll(views_str, '[^0-9]', ''))       AS views,
    images,
    source_url,
    toDate(nullIf(auctions.date_iso, ''))          AS auction_date,
    last_parsed_at,
    last_source_fetched_at,
    toUInt32OrNull(extract(auction_id, '^[0-9]+')) AS auction_id_num,
    final_price_str != ''                          AS has_final,
    toUInt64OrNull(replaceRegexpAll(final_price_str, '[^0-9]', ''))
        / nullIf(toUInt64OrNull(replaceRegexpAll(start_price_str, '[^0-9]', '')), 0)
                                                   AS final_to_start_ratio
FROM aggregated
LEFT JOIN auctions USING (auction_id);
