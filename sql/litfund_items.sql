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
)
SELECT
    auction_id,
    lot_number,
    argMaxIf(lot_index,   parsed_at, lot_index != '')        AS lot_index,
    argMaxIf(title,       parsed_at, title != '')            AS title,
    argMaxIf(description, parsed_at, description != '')       AS description,
    argMaxIf(start_price, parsed_at, start_price != '')      AS start_price,
    argMaxIf(leading_bid, parsed_at, leading_bid != '')      AS leading_bid,
    argMaxIf(final_price, parsed_at, final_price != '')      AS final_price,
    argMaxIf(reserve_not_met, parsed_at, final_price != '')  AS reserve_not_met,
    argMaxIf(views,       parsed_at, views != '')            AS views,
    argMaxIf(images,      parsed_at, length(images) > 0)     AS images,
    argMaxIf(source_url,  parsed_at, source_url != '')       AS source_url,
    max(parsed_at)         AS last_parsed_at,
    max(source_fetched_at) AS last_source_fetched_at
FROM extracted
GROUP BY auction_id, lot_number;
