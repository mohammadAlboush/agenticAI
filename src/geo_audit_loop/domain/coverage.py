"""Query-Intent-Coverage-Contracts (Session 4): fuer WELCHE Fragetypen wird man zitiert?

Die 12 Probe-Prompts tragen je einen ``QueryIntent`` (informational, how-to, vergleich,
definition, checkliste, troubleshooting). Eine **reine, deterministische** Domaenenfunktion
misst je Intent, wie sichtbar die Zieldomain ist (wie oft sie fuer Fragen dieses Typs zitiert
wird) — und deckt so **Blind Spots** auf: „wofuer bist du unsichtbar?". Kein LLM, kein RNG
(wie der Effekt-Analyst) -> bit-reproduzierbar (Projektregeln §7). Die vom Query-Generator
(LLM) vorgeschlagenen Luecken-Fragen fuellen die schwachen Intents.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from statistics import fmean
from typing import Final

from pydantic import Field

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.probe import ProbePrompt, ProbeResult, ProbeStatus, QueryIntent

INTENT_LABELS: Final[dict[QueryIntent, str]] = {
    QueryIntent.INFORMATIONAL: "Informationell",
    QueryIntent.HOWTO: "Anleitung (How-To)",
    QueryIntent.COMPARISON: "Vergleich",
    QueryIntent.DEFINITION: "Definition",
    QueryIntent.CHECKLIST: "Checkliste",
    QueryIntent.TROUBLESHOOTING: "Fehlererkennung",
}


class GeneratedQuery(FrozenModel):
    """Eine vom Query-Generator vorgeschlagene Luecken-Frage fuer einen schwachen Intent."""

    intent: QueryIntent
    text: str = Field(min_length=1)


class IntentCoverage(FrozenModel):
    """Sichtbarkeit der Zieldomain fuer einen Fragetyp ueber die OK-Baseline-Probes."""

    intent: QueryIntent
    n_prompts: int = Field(ge=0)  # Prompts dieses Intents
    n_covered: int = Field(ge=0)  # davon: in >=1 OK-Probe zitiert
    coverage_rate: float = Field(ge=0.0, le=1.0)  # n_covered / n_prompts (Breite)
    mean_citation_rate: float = Field(ge=0.0, le=1.0)  # mittlere Zitationsrate (Tiefe)


class CoverageReport(FrozenModel):
    """Query-Intent-Coverage eines Runs: fuer welche Fragetypen ist die Domain (un)sichtbar.

    Parallel zu ``TopFlopReport``/``EffectReport`` ein deterministisches Run-Artefakt; die
    ``suggested_queries`` (LLM, optional) fuellen die schwachen Intents. Fliesst (laufinvariant)
    in den Report-Fingerprint und wird ueber den ``StoragePort`` persistiert.
    """

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    generated_at: datetime
    n_probes: int = Field(ge=0)  # Anzahl OK-Baseline-Probes
    overall_citation_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    intents: tuple[IntentCoverage, ...] = ()  # schwaechster zuerst (deterministisch)
    weakest_intents: tuple[QueryIntent, ...] = ()  # coverage_rate < Schwelle -> Blind Spots
    suggested_queries: tuple[GeneratedQuery, ...] = ()  # LLM-Vorschlaege (leer, wenn nicht erzeugt)


def compute_coverage(
    prompts: Sequence[ProbePrompt],
    probes: Sequence[ProbeResult],
    target_domain: str,
    *,
    run_id: str,
    generated_at: datetime,
    weak_threshold: float = c.COVERAGE_WEAK_THRESHOLD,
) -> CoverageReport:
    """Bildet aus intent-getaggten Prompts + OK-Probes die Intent-Coverage (reine Funktion).

    Je Prompt wird die Ziel-Zitationsrate ueber seine OK-Probes gemittelt (``target_cited``);
    je Intent daraus Breite (``coverage_rate`` = Anteil zitierter Prompts) und Tiefe
    (``mean_citation_rate``). Prompts ohne Intent zaehlen nicht. Sortierung ist ein **totaler
    Ordnungsschluessel** (Coverage asc, dann Rate asc, dann Intent) -> deterministisch;
    Raten auf 6 Nachkommastellen gerundet (Bit-Reproduzierbarkeit).

    Args:
        prompts: Die (intent-getaggten) Probe-Prompts des Runs.
        probes: Die zu betrachtenden Probe-Ergebnisse (i.d.R. die Baseline-Phase).
        target_domain: Die auditierte Domain.
        run_id: Der Lauf, zu dem der Report gehoert.
        generated_at: Zeitstempel (injizierte Uhr).
        weak_threshold: Coverage-Rate, unter der ein Intent als Blind Spot gilt.

    Returns:
        Ein ``CoverageReport`` mit Coverage je Intent (schwaechster zuerst) + Blind-Spot-Liste.
    """
    ok = [r for r in probes if r.status is ProbeStatus.OK]
    n = len(ok)
    by_prompt: dict[str, list[ProbeResult]] = defaultdict(list)
    for result in ok:
        by_prompt[result.prompt_id].append(result)

    # Je Prompt: Ziel-Zitationsrate ueber seine OK-Probes; gruppiert nach Intent.
    per_intent_rates: dict[QueryIntent, list[float]] = defaultdict(list)
    per_intent_covered: dict[QueryIntent, int] = defaultdict(int)
    per_intent_count: dict[QueryIntent, int] = defaultdict(int)
    all_rates: list[float] = []
    for prompt in prompts:
        if prompt.intent is None:
            continue
        prompt_probes = by_prompt.get(prompt.prompt_id, [])
        rate = (
            fmean(1.0 if r.target_cited else 0.0 for r in prompt_probes) if prompt_probes else 0.0
        )
        per_intent_count[prompt.intent] += 1
        per_intent_rates[prompt.intent].append(rate)
        if any(r.target_cited for r in prompt_probes):
            per_intent_covered[prompt.intent] += 1
        all_rates.append(rate)

    intents = [
        IntentCoverage(
            intent=intent,
            n_prompts=count,
            n_covered=per_intent_covered[intent],
            coverage_rate=round(per_intent_covered[intent] / count, 6) if count else 0.0,
            mean_citation_rate=round(fmean(per_intent_rates[intent]), 6),
        )
        for intent, count in per_intent_count.items()
    ]
    # Schwaechster zuerst: Coverage asc, dann Rate asc, dann Intent (totaler Ordnungsschluessel).
    intents.sort(key=lambda i: (i.coverage_rate, i.mean_citation_rate, i.intent.value))
    weakest = tuple(i.intent for i in intents if i.coverage_rate < weak_threshold)
    overall = round(fmean(all_rates), 6) if all_rates else 0.0

    return CoverageReport(
        run_id=run_id,
        target_domain=target_domain,
        generated_at=generated_at,
        n_probes=n,
        overall_citation_rate=overall,
        intents=tuple(intents),
        weakest_intents=weakest,
    )
