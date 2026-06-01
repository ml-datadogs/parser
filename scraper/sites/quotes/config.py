from scraper.sites.base import LinkRules, SiteConfig

config = SiteConfig(
    name="quotes",
    allowed_domains=("quotes.toscrape.com",),
    start_urls=("https://quotes.toscrape.com/",),
    link_rules=LinkRules(
        allow=(r"/page/\d+/", r"/tag/[^/]+/page/\d+/", r"/author/[^/]+/"),
        restrict_css=("div.quote", "li.next"),
    ),
    download_delay=0.5,
)
