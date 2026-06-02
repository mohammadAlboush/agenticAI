"""Pure Parsing der advertools-JSONL-Zeilen zu ``PageInventory`` (kein I/O, testbar).

advertools schreibt eine JSON-Lines-Datei; Mehrfachwerte einer Seite sind mit ``@@``
verkettet, JSON-LD/OpenGraph liegen in eigenen Spalten. Diese Heuristik extrahiert die
fuer das Inventar relevanten Felder robust und ist unabhaengig vom Crawl-I/O.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from geo_audit_loop.domain.inventory import CrawledPage, PageInventory, SchemaInventory

_MULTI = "@@"
_KNOWN_TYPES = (
    "FAQPage",
    "Article",
    "NewsArticle",
    "BlogPosting",
    "Person",
    "Organization",
    "BreadcrumbList",
    "HowTo",
    "Product",
    "WebPage",
    "WebSite",
)
_ARTICLE_TYPES = ("Article", "NewsArticle", "BlogPosting")


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    """Parst JSON-Lines-Text zu einer Liste von Zeilen-Dicts (leere Zeilen ignoriert)."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def _first(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.split(_MULTI)[0].strip() or None if text else None


def _multi(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    text = str(value).strip()
    if not text:
        return ()
    return tuple(part.strip() for part in text.split(_MULTI) if part.strip())


def _status(row: dict[str, Any]) -> int:
    for key in ("status", "status_code"):
        raw = row.get(key)
        if raw is not None:
            try:
                return int(raw)
            except (TypeError, ValueError):
                continue
    return 0


def _detect_types(row: dict[str, Any]) -> tuple[str, ...]:
    blob = " ".join(str(v) for k, v in row.items() if "jsonld" in k.lower() and v is not None)
    return tuple(dict.fromkeys(t for t in _KNOWN_TYPES if t in blob))


def _has_opengraph(row: dict[str, Any]) -> bool:
    return any(key.lower().startswith(("og:", "og_")) for key in row)


def row_to_inventory(row: dict[str, Any]) -> PageInventory | None:
    """Bildet eine advertools-Zeile auf ein ``PageInventory`` ab (oder ``None`` ohne URL)."""
    url = _first(row.get("url"))
    if not url:
        return None
    body = row.get("body_text") or ""
    page = CrawledPage(
        url=url,
        status_code=_status(row),
        title=_first(row.get("title")),
        meta_description=_first(row.get("meta_desc")) or _first(row.get("meta_description")),
        h1=_multi(row.get("h1")),
        h2=_multi(row.get("h2")),
        word_count=len(str(body).split()),
        canonical=_first(row.get("canonical")),
        lang=_first(row.get("html_lang")) or _first(row.get("lang")),
    )
    types = _detect_types(row)
    schema_inventory = SchemaInventory(
        url=url,
        jsonld_types=types,
        has_faq="FAQPage" in types,
        has_article=any(t in types for t in _ARTICLE_TYPES),
        has_author="Person" in types,
        has_breadcrumb="BreadcrumbList" in types,
        has_opengraph=_has_opengraph(row),
    )
    return PageInventory(page=page, schema_inventory=schema_inventory)


def rows_to_inventory(rows: Iterable[dict[str, Any]]) -> list[PageInventory]:
    """Wandelt mehrere advertools-Zeilen in ein Seiten-Inventar (URL-lose verworfen)."""
    result: list[PageInventory] = []
    for row in rows:
        inventory = row_to_inventory(row)
        if inventory is not None:
            result.append(inventory)
    return result
