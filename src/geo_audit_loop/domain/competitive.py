"""Competitive-Intelligence-Contracts (Session 3): Zitations-Share-of-Voice einer Domain.

Aus denselben Baseline-Probes wie die Top/Flop-Messung leitet eine **reine, deterministische**
Domaenenfunktion ab, **welche externen Domains** (Wettbewerber) die AI-Engines fuer die Prompts
der Zieldomain zitieren — und wie oft relativ zur eigenen Domain. Das ist der "Share of Voice":
der Anteil der Antworten, in denen eine Domain als Quelle auftaucht. Kein LLM, kein RNG (wie der
Effekt-Analyst) -> bit-reproduzierbar (Projektregeln §7). Die Wettbewerber-Seiten sind die
Grundlage, um vom Feld zu lernen: Wer gewinnt die Zitate, und mit welchen Seiten?
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from pydantic import Field

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.metrics import host_matches_domain, normalize_url, url_host
from geo_audit_loop.domain.probe import ProbeResult, ProbeStatus


class DomainShare(FrozenModel):
    """Zitations-Anteil einer einzelnen Domain ueber die OK-Baseline-Probes eines Runs."""

    rank: int = Field(ge=1)  # 1-basierter Rang in der GESAMT-Rangfolge (auch wenn gekappt)
    domain: str = Field(min_length=1)  # Host, klein, ohne fuehrendes ``www.``
    citation_count: int = Field(ge=0)  # in wie vielen OK-Probes die Domain zitiert wurde
    citation_rate: float = Field(ge=0.0, le=1.0)  # citation_count / n_probes ("Share of Voice")
    is_target: bool  # ob dies die auditierte Zieldomain ist


class CompetitorPage(FrozenModel):
    """Eine konkrete (Nicht-Ziel-)Seite, die haeufig zitiert wird — ein Lern-Exemplar."""

    url: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    citation_count: int = Field(ge=0)


class ShareOfVoiceReport(FrozenModel):
    """Wettbewerbslandschaft eines Runs: wer gewinnt die Zitate fuer die Prompts der Zieldomain.

    Parallel zu ``TopFlopReport``/``EffectReport`` ein deterministisches Run-Artefakt; fliesst
    (laufinvariant) in den Report-Fingerprint und wird ueber den ``StoragePort`` persistiert.
    """

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    generated_at: datetime
    n_probes: int = Field(ge=0)  # Anzahl OK-Baseline-Probes (Nenner)
    target_rank: int | None = None  # 1-basierte Position der Zieldomain in ``shares`` (oder None)
    target_share: float = Field(default=0.0, ge=0.0, le=1.0)  # Share of Voice der Zieldomain
    shares: tuple[DomainShare, ...] = ()  # nach Haeufigkeit absteigend (deterministisch)
    top_competitor_pages: tuple[CompetitorPage, ...] = ()


def compute_share_of_voice(
    probes: Sequence[ProbeResult],
    target_domain: str,
    *,
    run_id: str,
    generated_at: datetime,
    top_domains: int = c.SOV_TOP_DOMAINS,
    top_pages: int = c.SOV_TOP_COMPETITOR_PAGES,
) -> ShareOfVoiceReport:
    """Bildet aus den OK-Probes den Share-of-Voice-Report (reine Domaenenfunktion, kein I/O).

    Zaehlweise **pro Probe** (Dedup wie ``count_target_url_citations``): eine Domain/Seite zaehlt
    hoechstens einmal je Antwort. ``citation_rate`` ist damit der Anteil der Antworten, in denen
    die Domain als Quelle auftaucht. Sortierung ist ein **totaler Ordnungsschluessel**
    (Haeufigkeit desc, dann Domain/URL asc) -> deterministisch.

    Args:
        probes: Die zu betrachtenden Probe-Ergebnisse (i.d.R. die Baseline-Phase eines Runs).
        target_domain: Die auditierte Domain (wird in ``shares`` markiert).
        run_id: Der Lauf, zu dem der Report gehoert.
        generated_at: Zeitstempel (injizierte Uhr) fuer das Artefakt.
        top_domains: Obergrenze der aufgelisteten Domains.
        top_pages: Obergrenze der aufgelisteten Wettbewerber-Seiten.

    Returns:
        Ein ``ShareOfVoiceReport`` mit rangierten Domain-Anteilen + Top-Wettbewerber-Seiten.
    """
    ok = [r for r in probes if r.status is ProbeStatus.OK]
    n = len(ok)
    domain_counts: dict[str, int] = defaultdict(int)
    page_counts: dict[str, int] = defaultdict(int)
    page_meta: dict[str, tuple[str, str]] = {}  # normalisierte URL -> (Anzeige-URL, Host)
    for result in ok:
        seen_domains: set[str] = set()
        seen_pages: set[str] = set()
        for cite in result.citations:
            host = url_host(cite.url)
            if not host:
                continue
            if host not in seen_domains:
                domain_counts[host] += 1
                seen_domains.add(host)
            key = normalize_url(cite.url)
            # Repraesentative Anzeige-URL: die lexikografisch KLEINSTE Roh-URL je Key ueber ALLE
            # Zitate (nicht first-seen) -> unabhaengig von der Probe-Reihenfolge, deterministisch.
            prev = page_meta.get(key)
            if prev is None or cite.url < prev[0]:
                page_meta[key] = (cite.url, host)
            if key not in seen_pages:
                page_counts[key] += 1
                seen_pages.add(key)

    # Rang in der GESAMT-Rangfolge (totaler Ordnungsschluessel: Haeufigkeit desc, dann Domain asc).
    ranked_pairs = sorted(domain_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    shares_all = [
        DomainShare(
            rank=position,
            domain=domain,
            citation_count=count,
            citation_rate=round(count / n, 6) if n else 0.0,
            is_target=host_matches_domain(domain, target_domain),
        )
        for position, (domain, count) in enumerate(ranked_pairs, start=1)
    ]
    target = next((s for s in shares_all if s.is_target), None)
    target_rank = target.rank if target is not None else None
    target_share = target.citation_rate if target is not None else 0.0

    # Top-Domains kappen, die Zieldomain aber IMMER behalten (auch wenn sie darunter rankt) —
    # so bleibt die "genau eine Ziel-Zeile"-Invariante erhalten, mit korrektem Rang.
    shares = list(shares_all[:top_domains])
    if target is not None and target not in shares:
        shares.append(target)

    competitor_pages = [
        CompetitorPage(url=page_meta[key][0], domain=page_meta[key][1], citation_count=count)
        for key, count in page_counts.items()
        if not host_matches_domain(page_meta[key][1], target_domain)
    ]
    competitor_pages.sort(key=lambda p: (-p.citation_count, p.url))  # totaler Ordnungsschluessel

    return ShareOfVoiceReport(
        run_id=run_id,
        target_domain=target_domain,
        generated_at=generated_at,
        n_probes=n,
        target_rank=target_rank,
        target_share=target_share,
        shares=tuple(shares),
        top_competitor_pages=tuple(competitor_pages[:top_pages]),
    )
