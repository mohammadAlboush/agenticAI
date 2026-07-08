"""Pure Aggregations- und Bewertungslogik ueber Probe-Ergebnisse (kein I/O).

Hier liegt die Domaenenmathematik des Samplers: Median ueber mehrere Proxy-IPs
(eliminiert Personalisierungs-Bias), Citation-/Mention-Rate und das Zaehlen der
zitierten Zieldomain-URLs (Grundlage der Top/Flop-Liste).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from statistics import median
from urllib.parse import urlsplit

from pydantic import Field

from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.probe import Citation, EngineId, ProbeResult, ProbeStatus


def url_host(url: str) -> str:
    """Extrahiert den Host einer URL (klein, ohne fuehrendes ``www.``)."""
    host = urlsplit(url.strip()).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def host_matches_domain(host: str, domain: str) -> bool:
    """Prueft, ob ``host`` zur Zieldomain gehoert (exakt oder als Subdomain)."""
    target = domain.strip().lower().lstrip(".")
    if target.startswith("www."):
        target = target[4:]
    return host == target or host.endswith("." + target)


def normalize_url(url: str) -> str:
    """Normalisiert eine URL fuer robustes Matching zwischen Zitat und Crawl.

    Host klein und ohne ``www.``, Fragment entfernt, Trailing-Slash vereinheitlicht.
    Query bleibt erhalten (kann eine Seite eindeutig machen).
    """
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    base = f"{scheme}://{host}{path}"
    return f"{base}?{parts.query}" if parts.query else base


def evaluate_target(citations: Sequence[Citation], target_domain: str) -> tuple[bool, int | None]:
    """Ermittelt, ob die Zieldomain zitiert wurde und an welcher Position (1-basiert).

    Liefert ``(cited, rank)``; ``rank`` ist die ``Citation.rank`` der ersten
    passenden Quelle (oder ihre 1-basierte Listenposition als Fallback).
    """
    for idx, cite in enumerate(citations, start=1):
        if host_matches_domain(url_host(cite.url), target_domain):
            return True, (cite.rank if cite.rank is not None else idx)
    return False, None


class ProbeAggregate(FrozenModel):
    """Aggregierte Sampler-Kennzahlen pro (Engine, Prompt) ueber alle Proxy-IPs."""

    engine_id: EngineId
    prompt_id: str = Field(min_length=1)
    n_probes: int = Field(ge=0)
    citation_rate: float = Field(ge=0.0, le=1.0)
    mention_rate: float = Field(ge=0.0, le=1.0)
    median_target_rank: float | None = None


class UrlCitationStat(FrozenModel):
    """Wie oft eine konkrete Zieldomain-URL ueber den Run zitiert wurde."""

    url: str = Field(min_length=1)
    citation_count: int = Field(ge=0)
    best_rank: int | None = None


def aggregate_probes(results: Iterable[ProbeResult]) -> list[ProbeAggregate]:
    """Gruppiert Probe-Ergebnisse nach (Engine, Prompt) und berechnet die Kennzahlen.

    Fehlerhafte Probes (``status != OK``) zaehlen nicht in den Nenner. Der Median
    der Zielposition wird nur ueber tatsaechlich zitierte Probes gebildet.
    """
    groups: dict[tuple[EngineId, str], list[ProbeResult]] = defaultdict(list)
    for result in results:
        groups[(result.engine_id, result.prompt_id)].append(result)

    aggregates: list[ProbeAggregate] = []
    ordered = sorted(groups.items(), key=lambda kv: (kv[0][0].value, kv[0][1]))
    for (engine_id, prompt_id), group in ordered:
        ok = [r for r in group if r.status is ProbeStatus.OK]
        n = len(ok)
        if n == 0:
            aggregates.append(
                ProbeAggregate(
                    engine_id=engine_id,
                    prompt_id=prompt_id,
                    n_probes=0,
                    citation_rate=0.0,
                    mention_rate=0.0,
                    median_target_rank=None,
                )
            )
            continue
        cited = [r for r in ok if r.target_cited]
        ranks = [float(r.target_rank) for r in cited if r.target_rank is not None]
        aggregates.append(
            ProbeAggregate(
                engine_id=engine_id,
                prompt_id=prompt_id,
                n_probes=n,
                citation_rate=len(cited) / n,
                mention_rate=sum(1 for r in ok if r.mentioned) / n,
                median_target_rank=median(ranks) if ranks else None,
            )
        )
    return aggregates


def url_citation_counts(results: Iterable[ProbeResult], url: str) -> tuple[int, int]:
    """Roh-Zaehlung ``(hits, n)``: OK-Probes, die genau diese URL zitieren, und OK-Probes total.

    Exakte Ganzzahlen sind die Grundlage der statistischen Effekt-Messung (Wilson/Newcombe,
    Sprint 5) — sie brauchen die Treffer- und Stichprobenzahlen, nicht die gerundete Rate.

    Args:
        results: Die zu betrachtenden Probe-Ergebnisse (z.B. eine Phase eines Runs).
        url: Die konkrete Zielseite, deren Zitationen gezaehlt werden.

    Returns:
        ``(hits, n)`` mit ``hits`` = zitierende OK-Probes und ``n`` = Anzahl OK-Probes;
        ``(0, 0)``, wenn keine OK-Probe vorliegt.
    """
    ok = [r for r in results if r.status is ProbeStatus.OK]
    n = len(ok)
    if n == 0:
        return 0, 0
    key = normalize_url(url)
    hits = sum(1 for r in ok if any(normalize_url(c.url) == key for c in r.citations))
    return hits, n


def url_citation_rate(results: Iterable[ProbeResult], url: str) -> tuple[float, int]:
    """Anteil der OK-Probes, in denen genau diese URL zitiert wurde, plus Nenner ``n``.

    Grundlage der Vorher/Nachher-Metrik einer ``EffectHypothesis`` (Sprint 4): die
    Rate ist rein deterministisch aus den persistierten Probes ableitbar (kein RNG).

    Args:
        results: Die zu betrachtenden Probe-Ergebnisse (z.B. eine Phase eines Runs).
        url: Die konkrete Zielseite, deren Zitationsrate gemessen wird.

    Returns:
        ``(rate, n)`` mit ``rate`` = Treffer/OK-Probes und ``n`` = Anzahl OK-Probes;
        ``(0.0, 0)``, wenn keine OK-Probe vorliegt.
    """
    hits, n = url_citation_counts(results, url)
    return (hits / n, n) if n else (0.0, 0)


def count_target_url_citations(
    results: Iterable[ProbeResult], target_domain: str
) -> list[UrlCitationStat]:
    """Zaehlt pro Zieldomain-URL, in wie vielen Probes sie zitiert wurde.

    Pro Probe wird jede URL hoechstens einmal gezaehlt. ``best_rank`` ist die
    beste (kleinste) je beobachtete Position. Ergebnis ist nach Haeufigkeit
    absteigend, dann nach URL sortiert (deterministisch).
    """
    counts: dict[str, int] = defaultdict(int)
    best_rank: dict[str, int] = {}
    for result in results:
        if result.status is not ProbeStatus.OK:
            continue
        seen: set[str] = set()
        for idx, cite in enumerate(result.citations, start=1):
            if not host_matches_domain(url_host(cite.url), target_domain):
                continue
            key = normalize_url(cite.url)
            rank = cite.rank if cite.rank is not None else idx
            if key not in seen:
                counts[key] += 1
                seen.add(key)
            if key not in best_rank or rank < best_rank[key]:
                best_rank[key] = rank
    stats = [
        UrlCitationStat(url=url, citation_count=count, best_rank=best_rank.get(url))
        for url, count in counts.items()
    ]
    stats.sort(key=lambda s: (-s.citation_count, s.url))
    return stats
