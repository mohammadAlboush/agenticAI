"""Entity- & Knowledge-Graph-Contracts (Session 8): wie klar deklariert die Domain ihre Entitaeten?

Adressiert den Hebel *Entitaeten-Klarheit* (``Lever.ENTITY_CLARITY``, Pyramide-Ebene
*Substanz*) in der Tiefe: AI-Engines zitieren eher Quellen, deren Entitaeten sie
eindeutig aufloesen koennen (Organisation als ``Organization`` mit ``sameAs``, Autor als
``Person``, stabile ``@id``). Diese **reine, deterministische** Domaenenfunktion baut aus
dem bereits gecrawlten Seiten-Inventar (JSON-LD-Typen, OpenGraph, Autor, Canonical) einen
Entity-Graph, bewertet je Seite eine Entitaeten-Klarheit und erzeugt den **kanonischen
JSON-LD-Block**, den die Domain haben sollte — semantische Infrastruktur statt Textblock.
Kein LLM, kein RNG -> bit-reproduzierbar (Projektregeln §7). Die LLM-gestuetzte
Entity-Extraktion aus Fliesstext (benannte Entitaeten, ``sameAs``-Kandidaten) ist der
klar abgegrenzte Folgeschritt.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from statistics import fmean
from typing import Final

from pydantic import Field

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.inventory import PageInventory


class EntityKind(StrEnum):
    """Herkunft eines Entity-Knotens im Graph (geschlossenes Vokabular, keine Magic Strings)."""

    BRAND = "brand"  # die Domain-Marke als (implizite) Organization-Entitaet
    SCHEMA_TYPE = "schema_type"  # ein tatsaechlich in JSON-LD deklarierter schema.org-Typ


class EntityNode(FrozenModel):
    """Ein Knoten des Entity-Graphs: eine Entitaet, die die Domain (nicht) deklariert."""

    name: str = Field(min_length=1)
    kind: EntityKind
    schema_type: str = Field(min_length=1)  # z.B. "Organization", "FAQPage", "Person"
    pages_declaring: int = Field(ge=0)  # Seiten, die diesen Typ in JSON-LD deklarieren
    coverage_rate: float = Field(ge=0.0, le=1.0)  # pages_declaring / n_pages


class PageEntityClarity(FrozenModel):
    """Deterministische Entitaeten-Klarheit einer Seite ueber eine feste Signal-Rubrik."""

    url: str = Field(min_length=1)
    clarity_score: float = Field(ge=0.0, le=1.0)  # gewichtete Summe der erfuellten Signale
    declares_organization: bool  # Organization/WebSite in JSON-LD deklariert
    has_opengraph: bool  # OpenGraph gibt Entitaets-Name/-Typ/-URL
    has_author: bool  # Autor als Person-Entitaet (E-E-A-T)
    has_canonical: bool  # stabile Kanonical-URL als @id-Anker
    has_lang: bool  # Sprach-Attribut (Entitaets-Disambiguierung)


class EntityGraphReport(FrozenModel):
    """Entity-/Knowledge-Graph eines Runs: Entitaeten, Klarheit je Seite, JSON-LD-Fix.

    Parallel zu ``TopFlopReport``/``CoverageReport`` ein deterministisches Run-Artefakt;
    fliesst (laufinvariant) in den Report-Fingerprint und wird ueber den ``StoragePort``
    persistiert. Die vom (spaeteren) Entity-Extractor benannten Entitaeten und ``sameAs``-
    Kandidaten verfeinern spaeter den ``recommended_jsonld``-Block.
    """

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    generated_at: datetime
    n_pages: int = Field(ge=0)
    brand_name: str = Field(min_length=1)
    mean_clarity: float = Field(default=0.0, ge=0.0, le=1.0)
    entities: tuple[EntityNode, ...] = ()  # Marke zuerst, dann nach Deckung (deterministisch)
    page_scores: tuple[PageEntityClarity, ...] = ()  # schwaechste zuerst
    weakest_pages: tuple[str, ...] = ()  # clarity_score < Schwelle -> Klarheits-Luecken
    # ``sameAs``-Autoritaets-URLs der Marke (Session 8, LLM-Entity-Extractor). Leer im rein
    # deterministischen Kern; der Extractor fuellt sie und regeneriert ``recommended_jsonld``.
    brand_same_as: tuple[str, ...] = ()
    recommended_jsonld: str = Field(min_length=1)  # kanonischer Organization-Block (der Fix)


#: Etiketten der Klarheits-Signale fuer die Praesentationsschicht (keine Magic Strings).
CLARITY_SIGNAL_LABELS: Final[dict[str, str]] = {
    "organization": "Organization-Schema",
    "opengraph": "OpenGraph",
    "author": "Autor (Person)",
    "canonical": "Kanonical-@id",
    "lang": "Sprach-Signal",
}


def brand_from_domain(domain: str) -> str:
    """Leitet den Marken-/Organisationsnamen deterministisch aus der Domain ab.

    Entfernt ein fuehrendes ``www.`` und die Top-Level-Domain und nimmt das
    Second-Level-Label (``www.it-sicherheit.de`` -> ``it-sicherheit``). Faellt auf die
    unveraenderte Domain zurueck, falls kein Punkt vorhanden ist. Rein, keine Netz-Aufloesung.
    """
    host = domain.strip().lower()
    if host.startswith("www."):
        host = host[4:]
    labels = [label for label in host.split(".") if label]
    if len(labels) >= 2:
        return labels[0]
    return host or domain


def render_organization_jsonld(brand: str, domain: str, *, same_as: Sequence[str] = ()) -> str:
    """Erzeugt den kanonischen Organization-JSON-LD-Block der Domain (deterministisch).

    Der Block ist der konkrete Fix-Vorschlag fuer den Hebel *Entitaeten-Klarheit*: eine
    stabile ``@id``, der Marken-Name, die kanonische URL und (falls bekannt) ``sameAs``-
    Verweise auf externe Autoritaets-Quellen. ``json.dumps`` mit ``sort_keys`` +
    festem Indent -> bit-identische Ausgabe fuer denselben Input (Fingerprint-faehig).

    Args:
        brand: Der Marken-/Organisationsname (aus ``brand_from_domain``).
        domain: Die Zieldomain (fuer ``url`` und ``@id``).
        same_as: Optionale externe Autoritaets-URLs (Wikipedia, Handelsregister, ...).

    Returns:
        Ein eingerueckter, kanonisch sortierter JSON-LD-String.
    """
    base_url = f"https://{domain}"
    block: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": f"{base_url}/#organization",
        "name": brand,
        "url": base_url,
    }
    if same_as:
        # Deduplizieren + sortieren -> deterministisch, unabhaengig von der Eingabereihenfolge.
        block["sameAs"] = sorted(set(same_as))
    return json.dumps(block, sort_keys=True, ensure_ascii=False, indent=2)


def _page_clarity(inventory: PageInventory) -> PageEntityClarity:
    """Bewertet die Entitaeten-Klarheit EINER Seite ueber die feste, gewichtete Rubrik."""
    schema = inventory.schema_inventory
    page = inventory.page
    declares_org = bool(set(schema.jsonld_types) & c.ORGANIZATION_SCHEMA_TYPES)
    signals: dict[str, bool] = {
        "organization": declares_org,
        "opengraph": schema.has_opengraph,
        "author": schema.has_author,
        "canonical": page.canonical is not None and page.canonical != "",
        "lang": page.lang is not None and page.lang != "",
    }
    score = sum(c.ENTITY_CLARITY_WEIGHTS[key] for key, present in signals.items() if present)
    return PageEntityClarity(
        url=page.url,
        clarity_score=round(score, 6),
        declares_organization=signals["organization"],
        has_opengraph=signals["opengraph"],
        has_author=signals["author"],
        has_canonical=signals["canonical"],
        has_lang=signals["lang"],
    )


def build_entity_graph(
    target_domain: str,
    pages: Sequence[PageInventory],
    *,
    run_id: str,
    generated_at: datetime,
    weak_threshold: float = c.ENTITY_CLARITY_WEAK_THRESHOLD,
) -> EntityGraphReport:
    """Baut aus dem Seiten-Inventar den Entity-Graph + die Entitaeten-Klarheit (reine Funktion).

    Knoten: die Marke als Organization plus je ein Knoten pro tatsaechlich in JSON-LD
    deklariertem schema.org-Typ (mit Deckungsrate ueber die Seiten). Je Seite eine
    deterministische Klarheits-Bewertung; ``weakest_pages`` sind Seiten unter der Schwelle.
    Sortierungen sind **totale Ordnungsschluessel** -> deterministisch; Raten auf 6
    Nachkommastellen gerundet (Bit-Reproduzierbarkeit, Projektregeln §7).

    Args:
        target_domain: Die auditierte Domain.
        pages: Das gecrawlte Seiten-Inventar des Runs.
        run_id: Der Lauf, zu dem der Report gehoert.
        generated_at: Zeitstempel (injizierte Uhr).
        weak_threshold: Klarheits-Score, unter dem eine Seite als Luecke gilt.

    Returns:
        Ein ``EntityGraphReport`` mit Entity-Knoten (Marke zuerst), Klarheit je Seite
        (schwaechste zuerst), Luecken-Liste und dem empfohlenen JSON-LD-Block.
    """
    n = len(pages)
    brand = brand_from_domain(target_domain)

    # Deklarierte schema.org-Typen ueber alle Seiten zaehlen.
    type_counts: dict[str, int] = defaultdict(int)
    org_declaring = 0
    for inventory in pages:
        types = set(inventory.schema_inventory.jsonld_types)
        for schema_type in types:
            type_counts[schema_type] += 1
        if types & c.ORGANIZATION_SCHEMA_TYPES:
            org_declaring += 1

    brand_node = EntityNode(
        name=brand,
        kind=EntityKind.BRAND,
        schema_type="Organization",
        pages_declaring=org_declaring,
        coverage_rate=round(org_declaring / n, 6) if n else 0.0,
    )
    schema_nodes = [
        EntityNode(
            name=schema_type,
            kind=EntityKind.SCHEMA_TYPE,
            schema_type=schema_type,
            pages_declaring=count,
            coverage_rate=round(count / n, 6) if n else 0.0,
        )
        for schema_type, count in type_counts.items()
    ]
    # Totaler Ordnungsschluessel: haeufigster Typ zuerst, dann alphabetisch (deterministisch).
    schema_nodes.sort(key=lambda node: (-node.pages_declaring, node.name))
    entities = (brand_node, *schema_nodes)

    scores = [_page_clarity(inventory) for inventory in pages]
    # Schwaechste zuerst: Score asc, dann URL (totaler Ordnungsschluessel).
    scores.sort(key=lambda s: (s.clarity_score, s.url))
    weakest = tuple(s.url for s in scores if s.clarity_score < weak_threshold)
    mean_clarity = round(fmean(s.clarity_score for s in scores), 6) if scores else 0.0

    return EntityGraphReport(
        run_id=run_id,
        target_domain=target_domain,
        generated_at=generated_at,
        n_pages=n,
        brand_name=brand,
        mean_clarity=mean_clarity,
        entities=entities,
        page_scores=tuple(scores),
        weakest_pages=weakest,
        recommended_jsonld=render_organization_jsonld(brand, target_domain),
    )
