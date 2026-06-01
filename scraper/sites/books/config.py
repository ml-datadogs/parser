from scraper.sites.base import LinkRules, SiteConfig

config = SiteConfig(
    name="books",
    allowed_domains=("books.toscrape.com",),
    start_urls=("https://books.toscrape.com/",),
    link_rules=LinkRules(
        allow=(r"catalogue/page-\d+\.html", r"catalogue/category/books/.*", r"catalogue/[^/]+_\d+/index\.html"),
        restrict_css=("article.product_pod", "li.next"),
    ),
    download_delay=0.5,
)
