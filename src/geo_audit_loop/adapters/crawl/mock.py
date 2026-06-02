"""Crawl-Adapter: deterministischer Mock (kein Netz) fuer Offline-Pipeline und Tests."""

from __future__ import annotations

from collections.abc import Sequence

from geo_audit_loop.adapters.sample_data import build_sample_inventory
from geo_audit_loop.domain.inventory import CrawlOptions, PageInventory


class MockCrawlAdapter:
    """Liefert ein vorgegebenes Seiten-Inventar (erfuellt ``CrawlPort``)."""

    def __init__(self, pages: Sequence[PageInventory] | None = None) -> None:
        self._pages: tuple[PageInventory, ...] = tuple(
            pages if pages is not None else build_sample_inventory()
        )

    def crawl(self, domain: str, options: CrawlOptions) -> list[PageInventory]:
        """Gibt das (ggf. injizierte) Inventar zurueck; respektiert ``max_pages``."""
        return list(self._pages[: options.max_pages])
