import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_NAME = "scraper"
SPIDER_MODULES = ["scraper.spiders"]
NEWSPIDER_MODULE = "scraper.spiders"

ROBOTSTXT_OBEY = True
USER_AGENT = "scraper-bot/1.0 (+https://example.com/bot)"

CONCURRENT_REQUESTS = 32
DOWNLOAD_DELAY = 0
REACTOR_THREADPOOL_MAXSIZE = 20
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0

RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [403, 429, 500, 502, 503, 504]

DOWNLOADER_MIDDLEWARES = {
    # Unlocker runs before the residential proxy: when it wraps a request the
    # proxy middleware skips it (auth is via Bearer token, not the proxy).
    "scraper.middlewares.BrightDataUnlockerMiddleware": 590,
    "scraper.middlewares.BrightDataProxyMiddleware": 610,
}

ITEM_PIPELINES = {
    "scraper.pipelines.JsonLinesExportPipeline": 300,
    "scraper.pipelines.ClickHouseRawPipeline": 400,
}

FEED_EXPORT_ENCODING = "utf-8"

# Bright Data
BRIGHTDATA_CUSTOMER = os.getenv("BRIGHTDATA_CUSTOMER", "")
BRIGHTDATA_ZONE = os.getenv("BRIGHTDATA_ZONE", "")
BRIGHTDATA_PASSWORD = os.getenv("BRIGHTDATA_PASSWORD", "")
BRIGHTDATA_HOST = os.getenv("BRIGHTDATA_HOST", "brd.superproxy.io")
BRIGHTDATA_PORT = int(os.getenv("BRIGHTDATA_PORT", "33335"))
BRIGHTDATA_COUNTRY = os.getenv("BRIGHTDATA_COUNTRY", "")
BRIGHTDATA_VERIFY_SSL = os.getenv("BRIGHTDATA_VERIFY_SSL", "false").lower() in {
    "1",
    "true",
    "yes",
}
# Bright Data Web Unlocker (API mode). When the token is set, sites that define
# an unlocker_zone are routed through the Unlocker API.
BRIGHTDATA_API_TOKEN = os.getenv("BRIGHTDATA_API_TOKEN", "")
BRIGHTDATA_API_URL = os.getenv(
    "BRIGHTDATA_API_URL", "https://api.brightdata.com/request"
)

# ClickHouse
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "scraper")
CLICKHOUSE_RAW_TABLE = os.getenv("CLICKHOUSE_RAW_TABLE", "raw_items")
CLICKHOUSE_BATCH_SIZE = int(os.getenv("CLICKHOUSE_BATCH_SIZE", "1000"))

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
