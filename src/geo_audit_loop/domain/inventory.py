"""Inventory-Contracts: gecrawlte Seite + strukturierte Daten."""

from __future__ import annotations

from pydantic import Field

from geo_audit_loop.domain._base import FrozenModel


class CrawlOptions(FrozenModel):
    """Konfiguration eines Inventory-Crawls (hoeflich und begrenzt, Projektregeln §6)."""

    max_pages: int = Field(default=200, gt=0)
    download_delay_s: float = Field(default=1.0, ge=0.0)
    concurrent_per_domain: int = Field(default=2, gt=0)
    respect_robots: bool = True
    user_agent: str = Field(min_length=1)


class CrawledPage(FrozenModel):
    """Technisches On-Page-Inventar einer URL."""

    url: str = Field(min_length=1)
    status_code: int
    title: str | None = None
    meta_description: str | None = None
    h1: tuple[str, ...] = ()
    h2: tuple[str, ...] = ()
    word_count: int = Field(default=0, ge=0)
    canonical: str | None = None
    lang: str | None = None


class SchemaInventory(FrozenModel):
    """Strukturierte-Daten-Inventar (Schema.org/JSON-LD, OpenGraph) einer URL."""

    url: str = Field(min_length=1)
    jsonld_types: tuple[str, ...] = ()
    has_faq: bool = False
    has_article: bool = False
    has_author: bool = False
    has_breadcrumb: bool = False
    has_opengraph: bool = False


class PageInventory(FrozenModel):
    """Zusammengefuehrtes Seiten-Inventar (Technik + strukturierte Daten)."""

    page: CrawledPage
    schema_inventory: SchemaInventory
