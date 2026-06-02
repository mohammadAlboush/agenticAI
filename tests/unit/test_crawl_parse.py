"""Phase-4-Gate: reines Parsing der advertools-JSONL-Zeilen."""

from __future__ import annotations

from geo_audit_loop.adapters.crawl._parse import parse_jsonl, row_to_inventory, rows_to_inventory


def test_parse_jsonl_skips_blank_lines() -> None:
    text = '{"url":"https://x.de/a"}\n\n{"url":"https://x.de/b"}\n'
    assert len(parse_jsonl(text)) == 2


def test_row_to_inventory_extracts_core_fields() -> None:
    row = {
        "url": "https://www.it-sicherheit.de/nis2",
        "status": 200,
        "title": "NIS2",
        "meta_desc": "Beschreibung",
        "h1": "NIS2",
        "h2": "Ueberblick@@Praxis",
        "canonical": "https://www.it-sicherheit.de/nis2",
        "body_text": "wort1 wort2 wort3",
        "html_lang": "de",
        "jsonld_0": '{"@type": "Article"}',
        "og:title": "NIS2",
    }
    inv = row_to_inventory(row)
    assert inv is not None
    assert inv.page.url == "https://www.it-sicherheit.de/nis2"
    assert inv.page.status_code == 200
    assert inv.page.h2 == ("Ueberblick", "Praxis")
    assert inv.page.word_count == 3
    assert inv.page.lang == "de"
    assert inv.schema_inventory.has_article is True
    assert inv.schema_inventory.has_opengraph is True


def test_row_to_inventory_detects_faq_and_breadcrumb() -> None:
    row = {"url": "https://x.de/p", "jsonld_a": "FAQPage", "jsonld_b": "BreadcrumbList"}
    inv = row_to_inventory(row)
    assert inv is not None
    assert inv.schema_inventory.has_faq is True
    assert inv.schema_inventory.has_breadcrumb is True


def test_row_without_url_returns_none() -> None:
    assert row_to_inventory({"title": "kein url"}) is None


def test_rows_to_inventory_filters_urlless() -> None:
    rows = [{"url": "https://x.de/a"}, {"title": "no url"}]
    assert len(rows_to_inventory(rows)) == 1
