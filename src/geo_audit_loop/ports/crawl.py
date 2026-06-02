"""Port: Crawlen einer Domain zu Seiten-Inventar."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from geo_audit_loop.domain.inventory import CrawlOptions, PageInventory


@runtime_checkable
class CrawlPort(Protocol):
    """Crawlt eine Domain und liefert je Seite ein ``PageInventory``.

    Implementierungen kapseln die Aussenwelt vollstaendig (der advertools-Adapter
    laeuft z.B. in einem Subprozess, um den Twisted-Reactor zu isolieren). Bei nicht
    behebbaren Fehlern wird ``CrawlError`` geworfen.
    """

    def crawl(self, domain: str, options: CrawlOptions) -> list[PageInventory]:
        """Crawlt ``domain`` hoeflich gemaess ``options`` und liefert das Seiten-Inventar."""
        ...
