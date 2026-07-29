"""Overlap-Contracts (Live-Loop): Google-Top-Treffer vs. AI-Zitate, pro Thema.

Macht die Kernthese messbar: wie stark ueberlappen die organischen Google-Treffer
einer Keyword-Query mit den Quellen, die AI-Engines zum selben Thema zitieren?
``compute_overlap`` ist eine reine Domaenenfunktion (kein I/O, kein LLM, kein RNG,
Muster ``form_effect_report``): Join ueber ``prompt_id``, URL-Normalisierung via
``normalize_url``, Rundung auf 6 Nachkommastellen, deterministische Sortierung
nach ``query_id`` — der Offline-Pfad (Mock-SERP) bleibt bit-reproduzierbar.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from statistics import fmean

from pydantic import Field

from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.metrics import host_matches_domain, normalize_url, url_host
from geo_audit_loop.domain.probe import ProbeResult, ProbeStatus
from geo_audit_loop.domain.serp import SerpProvider, SerpResult


class OverlapStat(FrozenModel):
    """Ueberlappungs-Kennzahlen fuer genau ein Thema (eine Query <-> ein Prompt).

    ``jaccard``/``ai_in_serp_share`` arbeiten auf normalisierter URL-Ebene,
    ``domain_jaccard`` auf Host-Ebene (robust gegen unterschiedliche Deep-Links).
    """

    query_id: str = Field(min_length=1)
    prompt_id: str = Field(min_length=1)
    jaccard: float = Field(ge=0.0, le=1.0)  # |Schnitt| / |Vereinigung| (URLs)
    ai_in_serp_share: float = Field(ge=0.0, le=1.0)  # Anteil AI-Zitate, die in der SERP stehen
    domain_jaccard: float = Field(ge=0.0, le=1.0)  # Jaccard auf Host-Ebene
    target_serp_rank: int | None = Field(default=None, ge=1)  # beste Ziel-Position (oder None)
    target_ai_citation_rate: float = Field(ge=0.0, le=1.0)  # Zitationsrate der Zieldomain
    n_serp_urls: int = Field(ge=0)  # Groesse der SERP-Menge (normalisierte URLs)
    n_ai_urls: int = Field(ge=0)  # Groesse der AI-Zitat-Menge (normalisierte URLs)


class OverlapReport(FrozenModel):
    """Run-Artefakt des Overlap-Vergleichs (persistiert, Upsert ueber ``run_id``)."""

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    generated_at: datetime
    provider: SerpProvider
    query_set_version: str = Field(min_length=1)
    n_queries: int = Field(ge=0)  # Anzahl ausgewerteter Queries (OK-SERP-Ergebnisse)
    mean_jaccard: float = Field(ge=0.0, le=1.0)
    mean_ai_in_serp_share: float = Field(ge=0.0, le=1.0)
    stats: tuple[OverlapStat, ...] = ()


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard-Index zweier Mengen; leere Vereinigung ergibt 0.0 (kein Signal)."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def compute_overlap(
    *,
    run_id: str,
    target_domain: str,
    provider: SerpProvider,
    query_set_version: str,
    serp_results: Sequence[SerpResult],
    probes: Sequence[ProbeResult],
    generated_at: datetime,
) -> OverlapReport:
    """Vergleicht je Thema die SERP-Treffer mit den AI-Zitaten (reine Domaenenfunktion).

    Join: jedes OK-SERP-Ergebnis wird ueber seine ``prompt_id`` mit den OK-Probes
    desselben Prompts verbunden (Engines/Proxies vereint — die AI-Zitatmenge ist die
    Vereinigung aller zitierten URLs des Themas). SERP-Ergebnisse mit ``status=ERROR``
    liefern keine belastbare Vergleichsmenge und werden uebersprungen.

    Args:
        run_id: Der Lauf, zu dem der Vergleich gehoert.
        target_domain: Die Zieldomain (fuer target_serp_rank/target_ai_citation_rate).
        provider: Quelle der SERP-Daten (mock/serper) — Reproduzierbarkeits-Klasse.
        query_set_version: Version des verwendeten SERP-Query-Sets (Provenienz).
        serp_results: Die SERP-Ergebnisse des Runs (eine Query je Ergebnis).
        probes: Die Probe-Ergebnisse, gegen die verglichen wird (z.B. Baseline-Phase).
        generated_at: Zeitstempel (injizierte Uhr) fuer das Artefakt.

    Returns:
        Ein ``OverlapReport`` mit einer ``OverlapStat`` je Query, sortiert nach
        ``query_id``; alle Quoten auf 6 Nachkommastellen gerundet (Bit-Stabilitaet).
    """
    ok_probes = [p for p in probes if p.status is ProbeStatus.OK]
    stats: list[OverlapStat] = []
    for serp in sorted(serp_results, key=lambda s: s.query_id):
        if serp.status is not ProbeStatus.OK:
            continue
        serp_urls = frozenset(normalize_url(e.url) for e in serp.entries)
        serp_hosts = frozenset(url_host(e.url) for e in serp.entries)
        topic_probes = [p for p in ok_probes if p.prompt_id == serp.prompt_id]
        ai_urls = frozenset(
            normalize_url(cite.url) for probe in topic_probes for cite in probe.citations
        )
        ai_hosts = frozenset(
            url_host(cite.url) for probe in topic_probes for cite in probe.citations
        )
        ai_in_serp = len(ai_urls & serp_urls) / len(ai_urls) if ai_urls else 0.0
        target_ranks = [
            e.position for e in serp.entries if host_matches_domain(url_host(e.url), target_domain)
        ]
        n_topic = len(topic_probes)
        cited = sum(1 for p in topic_probes if p.target_cited)
        stats.append(
            OverlapStat(
                query_id=serp.query_id,
                prompt_id=serp.prompt_id,
                jaccard=round(_jaccard(serp_urls, ai_urls), 6),
                ai_in_serp_share=round(ai_in_serp, 6),
                domain_jaccard=round(_jaccard(serp_hosts, ai_hosts), 6),
                target_serp_rank=min(target_ranks) if target_ranks else None,
                target_ai_citation_rate=round(cited / n_topic, 6) if n_topic else 0.0,
                n_serp_urls=len(serp_urls),
                n_ai_urls=len(ai_urls),
            )
        )
    mean_jaccard = round(fmean(s.jaccard for s in stats), 6) if stats else 0.0
    mean_share = round(fmean(s.ai_in_serp_share for s in stats), 6) if stats else 0.0
    return OverlapReport(
        run_id=run_id,
        target_domain=target_domain,
        generated_at=generated_at,
        provider=provider,
        query_set_version=query_set_version,
        n_queries=len(stats),
        mean_jaccard=mean_jaccard,
        mean_ai_in_serp_share=mean_share,
        stats=tuple(stats),
    )
