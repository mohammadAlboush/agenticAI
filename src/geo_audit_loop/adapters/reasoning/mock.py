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

# Konkrete Patches je Finding (Sprint 3): finding_id/target_url/template_id stimmen mit
# _AUDIT_FINDINGS ueberein; patch_id ist deterministisch (px-<finding>-<change_type>).
_FIX_PROPOSALS: dict[str, object] = {
    "proposals": [
        {
            "patch_id": "px-f1-insert_block",
            "finding_id": "f1",
            "target_url": f"{_BASE}/firewall-grundlagen",
            "lever": "fact_density",
            "pyramid_level": "substance",
            "change_type": "insert_block",
            "proposed_content": (
                "Eine Firewall filtert den Netzwerkverkehr anhand definierter Regeln. "
                "Moderne Stateful-Firewalls bewerten Verbindungszustaende; laut BSI-Grundschutz "
                "(Baustein NET.3.2) gehoeren Regelwerk-Reviews mindestens jaehrlich zum Standard."
            ),
            "rationale": (
                "Template t2 (Faktendichte) verlangt belegte Zahlen/Normen statt Marketing-Prosa "
                "— der Block ergaenzt konkrete BSI-Referenz und Pruefintervall."
            ),
            "confidence": 0.78,
            "template_id": "t2",
        },
        {
            "patch_id": "px-f2-add_schema",
            "finding_id": "f2",
            "target_url": f"{_BASE}/firewall-grundlagen",
            "lever": "definition_blocks",
            "pyramid_level": "extractability",
            "change_type": "add_schema",
            "proposed_content": (
                '{"@context":"https://schema.org","@type":"FAQPage","mainEntity":'
                '[{"@type":"Question","name":"Was ist eine Firewall?","acceptedAnswer":'
                '{"@type":"Answer","text":"Eine Firewall ist ein System, das Netzwerkverkehr '
                'anhand von Regeln zulaesst oder blockiert."}}]}'
            ),
            "rationale": (
                "Template t1 (Antwortblock + FAQ-Schema) verlangt maschinenlesbare Definitionen "
                "— FAQPage-JSON-LD macht den Kernbegriff extrahierbar."
            ),
            "confidence": 0.74,
            "template_id": "t1",
        },
        {
            "patch_id": "px-f3-insert_block",
            "finding_id": "f3",
            "target_url": f"{_BASE}/passwort-manager-vergleich",
            "lever": "machine_readable",
            "pyramid_level": "extractability",
            "change_type": "insert_block",
            "proposed_content": (
                "| Passwort-Manager | Open Source | 2FA | Preis/Jahr |\n"
                "|---|---|---|---|\n| Bitwarden | ja | ja | 0-10 EUR |\n"
                "| KeePassXC | ja | ueber Plugin | 0 EUR |\n| 1Password | nein | ja | 36 EUR |"
            ),
            "rationale": (
                "Template t1 verlangt extrahierbare Struktur — eine Vergleichstabelle ersetzt den "
                "Fliesstext und bedient den Query-Fan-out (Preis, 2FA, Open Source)."
            ),
            "confidence": 0.80,
            "template_id": "t1",
        },
        {
            "patch_id": "px-f4-add_schema",
            "finding_id": "f4",
            "target_url": f"{_BASE}/passwort-manager-vergleich",
            "lever": "entity_clarity",
            "pyramid_level": "substance",
            "change_type": "add_schema",
            "proposed_content": (
                '{"@context":"https://schema.org","@type":"Article","author":'
                '{"@type":"Person","name":"Redaktion IT-Sicherheit"},'
                '"dateModified":"2026-06-01"}'
            ),
            "rationale": (
                "Template t2 (Autor-Entitaet) verlangt eine klare Quelle — Person-Schema plus "
                "sichtbares dateModified erhoehen Vertrauen und Aktualitaetssignal."
            ),
            "confidence": 0.72,
            "template_id": "t2",
        },
        {
            "patch_id": "px-f5-insert_block",
            "finding_id": "f5",
            "target_url": f"{_BASE}/security-awareness-training",
            "lever": "answer_blocks",
            "pyramid_level": "extractability",
            "change_type": "insert_block",
            "proposed_content": (
                "Security-Awareness-Training schult Mitarbeitende darin, Phishing, Social "
                "Engineering und unsichere Passwoerter zu erkennen. Wirksame Programme kombinieren "
                "kurze Lerneinheiten mit simulierten Angriffen und messen die Klickrate ueber Zeit."
            ),
            "rationale": (
                "Template t1 verlangt einen 40-60-Woerter-Antwortblock direkt unter der H1 — der "
                "Block ist eigenstaendig zitierbar."
            ),
            "confidence": 0.77,
            "template_id": "t1",
        },
        {
            "patch_id": "px-f6-insert_block",
            "finding_id": "f6",
            "target_url": f"{_BASE}/security-awareness-training",
            "lever": "query_coverage",
            "pyramid_level": "citation",
            "change_type": "insert_block",
            "proposed_content": (
                "FAQ: Was kostet ein Security-Awareness-Training? Wie oft sollte es stattfinden? "
                "Welche Tools eignen sich? — jede Teilfrage als eigener H3-Abschnitt mit "
                "praegnanter Antwort."
            ),
            "rationale": (
                "Template t3 (Frage-Deckung) verlangt explizite Teilfragen des Query-Fan-out — "
                "die FAQ deckt Kosten, Haeufigkeit und Tools ab."
            ),
            "confidence": 0.69,
            "template_id": "t3",
        },
    ]
}

# sameAs-Autoritaets-URLs der Beispiel-Marke (Session 8, Entity-Extractor): stabile,
# offizielle Quellen, auf die das Organization-Schema verweisen sollte. Enthaelt bewusst
# eine Dublette + eine relative URL, damit der Agent-Filter (Dedupe/URL-Validierung) greift.
_EXTRACTED_ENTITIES: dict[str, object] = {
    "same_as": [
        "https://de.wikipedia.org/wiki/IT-Sicherheit",
        "https://www.wikidata.org/wiki/Q3968",
        "https://de.wikipedia.org/wiki/IT-Sicherheit",
        "/nur-relativ-kein-authoritaets-ziel",
        "https://www.linkedin.com/company/it-sicherheit",
    ]
}

_PAYLOADS: dict[str, dict[str, object]] = {
    "pattern_miner": _PATTERN_TEMPLATES,
    "geo_auditor": _AUDIT_FINDINGS,
    "fix_agent": _FIX_PROPOSALS,
    "entity_extractor": _EXTRACTED_ENTITIES,
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
