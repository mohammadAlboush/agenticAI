"""Unit: Entity-/Knowledge-Graph — reine, deterministische Domaenenfunktion (Session 8)."""

from __future__ import annotations

import json
from datetime import datetime

from geo_audit_loop.domain.entity import (
    EntityKind,
    brand_from_domain,
    build_entity_graph,
    render_organization_jsonld,
)
from geo_audit_loop.domain.inventory import CrawledPage, PageInventory, SchemaInventory

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _page(
    url: str,
    *,
    jsonld_types: tuple[str, ...] = (),
    has_opengraph: bool = False,
    has_author: bool = False,
    canonical: str | None = None,
    lang: str | None = None,
) -> PageInventory:
    return PageInventory(
        page=CrawledPage(url=url, status_code=200, canonical=canonical, lang=lang),
        schema_inventory=SchemaInventory(
            url=url,
            jsonld_types=jsonld_types,
            has_opengraph=has_opengraph,
            has_author=has_author,
        ),
    )


def test_brand_from_domain_strips_www_and_tld() -> None:
    assert brand_from_domain("it-sicherheit.de") == "it-sicherheit"
    assert brand_from_domain("www.example.co.uk") == "example"
    assert brand_from_domain("EXAMPLE.COM") == "example"
    assert brand_from_domain("localhost") == "localhost"  # kein Punkt -> unveraendert


def test_render_jsonld_is_canonical_and_deterministic() -> None:
    a = render_organization_jsonld("it-sicherheit", "it-sicherheit.de")
    b = render_organization_jsonld("it-sicherheit", "it-sicherheit.de")
    assert a == b
    block = json.loads(a)
    assert block["@type"] == "Organization"
    assert block["name"] == "it-sicherheit"
    assert block["@id"] == "https://it-sicherheit.de/#organization"
    assert block["url"] == "https://it-sicherheit.de"
    assert "sameAs" not in block  # ohne Vorgabe kein leeres sameAs


def test_render_jsonld_same_as_sorted_and_deduped() -> None:
    block = json.loads(
        render_organization_jsonld(
            "brand",
            "example.com",
            same_as=("https://b.example", "https://a.example", "https://b.example"),
        )
    )
    assert block["sameAs"] == ["https://a.example", "https://b.example"]


def test_clarity_rubric_full_and_empty() -> None:
    pages = [
        _page(
            "https://it-sicherheit.de/a",
            jsonld_types=("Organization", "FAQPage"),
            has_opengraph=True,
            has_author=True,
            canonical="https://it-sicherheit.de/a",
            lang="de",
        ),
        _page("https://it-sicherheit.de/b"),  # keinerlei Signale
    ]
    report = build_entity_graph("it-sicherheit.de", pages, run_id="run-1", generated_at=FIXED)
    by_url = {s.url: s for s in report.page_scores}
    assert by_url["https://it-sicherheit.de/a"].clarity_score == 1.0  # alle Gewichte
    assert by_url["https://it-sicherheit.de/b"].clarity_score == 0.0
    assert report.mean_clarity == 0.5
    assert report.weakest_pages == ("https://it-sicherheit.de/b",)  # 0.0 < 0.5
    # Schwaechste zuerst.
    assert report.page_scores[0].url == "https://it-sicherheit.de/b"


def test_partial_rubric_weight_sum() -> None:
    pages = [
        _page("https://d/x", canonical="https://d/x", lang="de"),  # 0.15 + 0.10
    ]
    report = build_entity_graph("d.de", pages, run_id="run-1", generated_at=FIXED)
    assert report.page_scores[0].clarity_score == 0.25


def test_entity_nodes_brand_first_then_by_coverage() -> None:
    pages = [
        _page("https://d/a", jsonld_types=("Organization", "FAQPage")),
        _page("https://d/b", jsonld_types=("FAQPage",)),
    ]
    report = build_entity_graph("d.de", pages, run_id="run-1", generated_at=FIXED)
    brand = report.entities[0]
    assert brand.kind is EntityKind.BRAND
    assert brand.name == "d"
    assert brand.pages_declaring == 1  # nur Seite a deklariert Organization
    assert brand.coverage_rate == 0.5
    schema_nodes = report.entities[1:]
    # FAQPage (2 Seiten) vor Organization (1 Seite): haeufigster zuerst.
    assert [n.schema_type for n in schema_nodes] == ["FAQPage", "Organization"]
    assert schema_nodes[0].pages_declaring == 2


def test_schema_nodes_tie_break_alphabetical() -> None:
    pages = [_page("https://d/a", jsonld_types=("WebSite", "Article"))]
    report = build_entity_graph("d.de", pages, run_id="run-1", generated_at=FIXED)
    schema_nodes = report.entities[1:]
    # Beide auf 1 Seite -> alphabetisch: Article vor WebSite.
    assert [n.schema_type for n in schema_nodes] == ["Article", "WebSite"]


def test_empty_pages_do_not_crash() -> None:
    report = build_entity_graph("d.de", [], run_id="run-1", generated_at=FIXED)
    assert report.n_pages == 0
    assert report.mean_clarity == 0.0
    assert report.entities[0].kind is EntityKind.BRAND  # Marke ist immer da
    assert report.recommended_jsonld  # Fix-Vorlage auch ohne Seiten


def test_determinism_same_inputs_same_report() -> None:
    pages = [_page("https://d/a", jsonld_types=("Organization",), has_opengraph=True)]
    a = build_entity_graph("d.de", pages, run_id="run-1", generated_at=FIXED)
    b = build_entity_graph("d.de", pages, run_id="run-1", generated_at=FIXED)
    assert a == b
