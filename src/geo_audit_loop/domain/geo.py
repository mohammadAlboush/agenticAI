"""GEO-Bewertungsrahmen: die 10 Zitations-Hebel und die Citation-Pyramide.

Verankert die inhaltlichen Agenten (Pattern-Miner, GEO-Auditor) in einem festen,
nachvollziehbaren Kriterienkatalog (Skill ``geo-strategy``). Kern-Vokabular ohne I/O:
jeder ``Template``/``AuditFinding`` laesst sich auf einen ``Lever`` und eine
``PyramidLevel`` zurueckbinden (keine Magic Strings, Projektregeln §4).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class PyramidLevel(StrEnum):
    """Ebenen der Citation-Pyramid (Basis -> Spitze). Ein Defizit unten entwertet oben."""

    ACCESS = "access"  # Ebene 1: Zugang & Indexierbarkeit
    EXTRACTABILITY = "extractability"  # Ebene 2: Extrahierbarkeit & Struktur
    SUBSTANCE = "substance"  # Ebene 3: Substanz & Vertrauen
    CORROBORATION = "corroboration"  # Ebene 4: Korroboration & Autoritaet
    CITATION = "citation"  # Spitze: tatsaechliche Zitation


class Lever(StrEnum):
    """Die 10 Hebel, die die Zitation in AI-Engines treiben (Skill ``geo-strategy``)."""

    CRAWLER_ACCESS = "crawler_access"
    ANSWER_BLOCKS = "answer_blocks"
    HEADING_HIERARCHY = "heading_hierarchy"
    DEFINITION_BLOCKS = "definition_blocks"
    FACT_DENSITY = "fact_density"
    MACHINE_READABLE = "machine_readable"
    ENTITY_CLARITY = "entity_clarity"
    FRESHNESS = "freshness"
    EXTERNAL_CORROBORATION = "external_corroboration"
    QUERY_COVERAGE = "query_coverage"


PYRAMID_ORDER: Final[dict[PyramidLevel, int]] = {
    PyramidLevel.ACCESS: 1,
    PyramidLevel.EXTRACTABILITY: 2,
    PyramidLevel.SUBSTANCE: 3,
    PyramidLevel.CORROBORATION: 4,
    PyramidLevel.CITATION: 5,
}

LEVER_PYRAMID: Final[dict[Lever, PyramidLevel]] = {
    Lever.CRAWLER_ACCESS: PyramidLevel.ACCESS,
    Lever.ANSWER_BLOCKS: PyramidLevel.EXTRACTABILITY,
    Lever.HEADING_HIERARCHY: PyramidLevel.EXTRACTABILITY,
    Lever.DEFINITION_BLOCKS: PyramidLevel.EXTRACTABILITY,
    Lever.MACHINE_READABLE: PyramidLevel.EXTRACTABILITY,
    Lever.FACT_DENSITY: PyramidLevel.SUBSTANCE,
    Lever.ENTITY_CLARITY: PyramidLevel.SUBSTANCE,
    Lever.FRESHNESS: PyramidLevel.SUBSTANCE,
    Lever.EXTERNAL_CORROBORATION: PyramidLevel.CORROBORATION,
    Lever.QUERY_COVERAGE: PyramidLevel.CITATION,
}

LEVER_LABELS: Final[dict[Lever, str]] = {
    Lever.CRAWLER_ACCESS: "Crawler-Zugang",
    Lever.ANSWER_BLOCKS: "Antwortbloecke",
    Lever.HEADING_HIERARCHY: "Ueberschriften-Hierarchie",
    Lever.DEFINITION_BLOCKS: "Definitionsbloecke",
    Lever.FACT_DENSITY: "Faktendichte & neutraler Ton",
    Lever.MACHINE_READABLE: "Maschinenlesbare Struktur",
    Lever.ENTITY_CLARITY: "Entitaeten-Klarheit",
    Lever.FRESHNESS: "Aktualitaets-Signale",
    Lever.EXTERNAL_CORROBORATION: "Externe Korroboration",
    Lever.QUERY_COVERAGE: "Frage-Deckung",
}

PYRAMID_LABELS: Final[dict[PyramidLevel, str]] = {
    PyramidLevel.ACCESS: "Zugang & Indexierbarkeit",
    PyramidLevel.EXTRACTABILITY: "Extrahierbarkeit & Struktur",
    PyramidLevel.SUBSTANCE: "Substanz & Vertrauen",
    PyramidLevel.CORROBORATION: "Korroboration & Autoritaet",
    PyramidLevel.CITATION: "Tatsaechliche Zitation",
}


def pyramid_rank(level: PyramidLevel) -> int:
    """Numerische Ordnung (1=Basis ... 5=Spitze) fuer die Findings-Priorisierung."""
    return PYRAMID_ORDER[level]
