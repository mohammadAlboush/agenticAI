"""Reasoning-Adapter: deterministischer Mock (kein Netz) fuer Offline-Pipeline und Evals.

Liefert je Agentenschritt (``task``) eine stabile, schema-valide JSON-Antwort, die der
Agent in ``Template``s bzw. ``AuditFinding``s parst. Inhaltlich an der Beispiel-Domain
``it-sicherheit.de`` (siehe ``adapters/sample_data.py``) verankert -- eine reproduzierbare
Fixture, KEIN echtes Reasoning. So bleibt die gesamte Lern-Pipeline offline deterministisch
(gleicher Seed -> gleicher PatternReport/AuditReport, Grundlage der toleranzbasierten Evals).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

from geo_audit_loop.domain.reasoning import (
    ReasoningRequest,
    ReasoningResult,
    ReasoningStatus,
    ReasoningUsage,
)

MOCK_MODEL = "mock-reasoner-v1"
_BASE = "https://www.it-sicherheit.de"

# Aus den Top-Seiten (Article + FAQ/HowTo, Autor, hohe Wortzahl) abgeleitete Muster.
_PATTERN_TEMPLATES: dict[str, object] = {
    "templates": [
        {
            "template_id": "t1",
            "title": "Extrahierbarer Antwortblock + FAQ-Schema",
            "summary": (
                "Top-Seiten liefern direkt nach der Ueberschrift einen eigenstaendigen "
                "40-60-Woerter-Antwortblock und kennzeichnen Q&A per FAQPage-Schema."
            ),
            "levers": ["answer_blocks", "machine_readable"],
            "pyramid_level": "extractability",
            "criteria": [
                "Article + FAQPage JSON-LD vorhanden",
                "40-60-Woerter-Antwort direkt nach der Ueberschrift",
                "Antwort als normaler Absatz, nicht im Callout-/Zitatkasten",
            ],
            "evidence_urls": [f"{_BASE}/nis2-richtlinie", f"{_BASE}/phishing-erkennen"],
            "confidence": 0.82,
        },
        {
            "template_id": "t2",
            "title": "Autor-Entitaet + Faktendichte",
            "summary": (
                "Zitierte Seiten nennen einen Autor (Person-Schema) und belegen Aussagen mit "
                "konkreten Zahlen, Fristen und Quellen statt Marketing-Prosa."
            ),
            "levers": ["entity_clarity", "fact_density"],
            "pyramid_level": "substance",
            "criteria": [
                "Autor-/Person-Schema gesetzt",
                "konkrete Zahlen/Fristen im Text",
                "neutraler, sachlicher Ton",
            ],
            "evidence_urls": [f"{_BASE}/nis2-richtlinie", f"{_BASE}/ransomware-schutz"],
            "confidence": 0.76,
        },
        {
            "template_id": "t3",
            "title": "Schritt-fuer-Schritt-Struktur (HowTo)",
            "summary": (
                "Anleitungsseiten gliedern den Inhalt in saubere H2/H3-Schritte und spiegeln das "
                "als HowTo-Schema -- gut fuer den Query-Fan-out."
            ),
            "levers": ["heading_hierarchy", "machine_readable", "query_coverage"],
            "pyramid_level": "extractability",
            "criteria": [
                "HowTo-Schema bei Anleitungen",
                "H1 -> H2 -> H3 sauber geschachtelt",
                "Teilfragen explizit als eigene Abschnitte",
            ],
            "evidence_urls": [f"{_BASE}/zero-trust-architektur", f"{_BASE}/dsgvo-checkliste"],
            "confidence": 0.71,
        },
    ]
}

# Findings fuer die Flop-Seiten (selten zitiert), gegen die Templates gehalten.
_AUDIT_FINDINGS: dict[str, object] = {
    "findings": [
        {
            "finding_id": "f1",
            "target_url": f"{_BASE}/firewall-grundlagen",
            "lever": "fact_density",
            "pyramid_level": "substance",
            "severity": "high",
            "evidence": "Nur ~600 Woerter, kein Autor-Schema, kaum konkrete Zahlen.",
            "recommendation": (
                "Inhalt mit belegten Fakten/Zahlen vertiefen und Autor-Schema setzen."
            ),
            "template_id": "t2",
        },
        {
            "finding_id": "f2",
            "target_url": f"{_BASE}/firewall-grundlagen",
            "lever": "definition_blocks",
            "pyramid_level": "extractability",
            "severity": "medium",
            "evidence": (
                "Keine FAQ-/Definitionsbloecke; Kernbegriffe nicht eigenstaendig definiert."
            ),
            "recommendation": (
                "FAQPage-Schema + kurze Definitionsabsaetze je Kernbegriff ergaenzen."
            ),
            "template_id": "t1",
        },
        {
            "finding_id": "f3",
            "target_url": f"{_BASE}/passwort-manager-vergleich",
            "lever": "machine_readable",
            "pyramid_level": "extractability",
            "severity": "high",
            "evidence": "Vergleich liegt nur als Fliesstext vor -- keine Tabelle/kein Markup.",
            "recommendation": "Vergleichstabelle + Product/Review-Schema ergaenzen.",
            "template_id": "t1",
        },
        {
            "finding_id": "f4",
            "target_url": f"{_BASE}/passwort-manager-vergleich",
            "lever": "entity_clarity",
            "pyramid_level": "substance",
            "severity": "medium",
            "evidence": "Kein Autor-Schema, kein sichtbares Aktualitaetsdatum.",
            "recommendation": "Autor-/Person-Schema und sichtbares dateModified setzen.",
            "template_id": "t2",
        },
        {
            "finding_id": "f5",
            "target_url": f"{_BASE}/security-awareness-training",
            "lever": "answer_blocks",
            "pyramid_level": "extractability",
            "severity": "medium",
            "evidence": "Kein extrahierbarer 40-60-Woerter-Antwortblock direkt nach der H1.",
            "recommendation": "Praegnanten Antwortblock direkt unter die H1 setzen.",
            "template_id": "t1",
        },
        {
            "finding_id": "f6",
            "target_url": f"{_BASE}/security-awareness-training",
            "lever": "query_coverage",
            "pyramid_level": "citation",
            "severity": "low",
            "evidence": "Teilfragen des Query-Fan-out (Kosten, Haeufigkeit, Tools) fehlen.",
            "recommendation": "FAQ mit den haeufigsten Teilfragen ergaenzen.",
            "template_id": "t3",
        },
    ]
}

_PAYLOADS: dict[str, dict[str, object]] = {
    "pattern_miner": _PATTERN_TEMPLATES,
    "geo_auditor": _AUDIT_FINDINGS,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MockReasoningAdapter:
    """Deterministischer Reasoning-Mock (erfuellt ``ReasoningPort``)."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock if clock is not None else _utc_now

    @property
    def model(self) -> str:
        """Modell-Label des Mocks."""
        return MOCK_MODEL

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        """Liefert die deterministische, schema-valide JSON-Antwort fuer ``request.task``."""
        payload = _PAYLOADS.get(request.task, {})
        text = json.dumps(payload, ensure_ascii=False)
        usage = ReasoningUsage(input_tokens=400, output_tokens=300, total_tokens=700)
        return ReasoningResult(
            run_id=request.run_id,
            task=request.task,
            model=MOCK_MODEL,
            text=text,
            usage=usage,
            status=ReasoningStatus.OK,
            generated_at=self._clock(),
        )
