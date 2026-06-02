"""Phase-4-Gate: Mock-Crawl-Adapter liefert reproduzierbares Inventar."""

from __future__ import annotations

from geo_audit_loop.adapters.crawl.mock import MockCrawlAdapter
from geo_audit_loop.adapters.sample_data import build_sample_inventory
from geo_audit_loop.domain.inventory import CrawlOptions


def test_returns_full_sample_inventory() -> None:
    crawler = MockCrawlAdapter()
    pages = crawler.crawl("it-sicherheit.de", CrawlOptions(user_agent="test"))
    assert len(pages) == len(build_sample_inventory())
    assert all(p.page.url.startswith("https://www.it-sicherheit.de/") for p in pages)


def test_respects_max_pages() -> None:
    crawler = MockCrawlAdapter()
    pages = crawler.crawl("d", CrawlOptions(user_agent="t", max_pages=3))
    assert len(pages) == 3


def test_returns_injected_pages() -> None:
    sample = build_sample_inventory()[:2]
    crawler = MockCrawlAdapter(sample)
    assert crawler.crawl("d", CrawlOptions(user_agent="t")) == sample
