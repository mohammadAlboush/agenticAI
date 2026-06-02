"""Inventory-Crawler-Service: Seiten-Inventar + Join mit Sampler-Daten -> Top/Flop.

Crawlt die Zieldomain (``CrawlPort``), persistiert das Inventar, zaehlt je gecrawlter
URL die Zitate aus den Sampler-Probes und baut den ``TopFlopReport`` (die Sprint-1-Demo:
neutrale Sichtbarkeits-Rangliste). Haengt nur an domain, ports und observability.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from geo_audit_loop.domain.findings import PageScore, TopFlopEntry, TopFlopReport
from geo_audit_loop.domain.inventory import CrawlOptions, PageInventory
from geo_audit_loop.domain.metrics import (
    ProbeAggregate,
    count_target_url_citations,
    normalize_url,
)
from geo_audit_loop.domain.probe import ProbeResult, ProbeStatus
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.ports.crawl import CrawlPort
from geo_audit_loop.ports.storage import StoragePort

_AGENT = "inventory_crawler"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InventoryCrawlerService:
    """Erzeugt Seiten-Inventar und den Top/Flop-Report eines Runs."""

    def __init__(
        self,
        *,
        crawl: CrawlPort,
        storage: StoragePort,
        logger: logging.Logger | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._crawl = crawl
        self._storage = storage
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._clock = clock if clock is not None else _utc_now

    def run(
        self,
        run_context: RunContext,
        options: CrawlOptions,
        *,
        aggregates: Sequence[ProbeAggregate],
        top_n: int,
    ) -> TopFlopReport:
        """Crawlt, persistiert Inventar und baut + speichert den Top/Flop-Report."""
        pages = self._crawl.crawl(run_context.target_domain, options)
        self._storage.save_pages(run_context.run_id, pages)
        probes = self._storage.load_probes(run_context.run_id)
        scores = self._score_pages(pages, probes, run_context.target_domain)
        report = self._build_report(run_context, pages, scores, aggregates, top_n)
        self._storage.save_report(report)
        log_event(
            self._log,
            "inventory.done",
            run_id=run_context.run_id,
            agent=_AGENT,
            n_pages=len(pages),
            n_probes=report.n_probes,
        )
        return report

    def _score_pages(
        self, pages: Sequence[PageInventory], probes: Sequence[ProbeResult], target_domain: str
    ) -> list[PageScore]:
        stats = {s.url: s for s in count_target_url_citations(probes, target_domain)}
        n_probes = sum(1 for probe in probes if probe.status is ProbeStatus.OK)
        scores: list[PageScore] = []
        for inventory in pages:
            stat = stats.get(normalize_url(inventory.page.url))
            count = stat.citation_count if stat is not None else 0
            best_rank = stat.best_rank if stat is not None else None
            rate = count / n_probes if n_probes else 0.0
            scores.append(
                PageScore(
                    url=inventory.page.url,
                    citation_count=count,
                    n_probes=n_probes,
                    citation_rate=rate,
                    best_rank=best_rank,
                    inventory=inventory,
                )
            )
        return scores

    def _build_report(
        self,
        run_context: RunContext,
        pages: Sequence[PageInventory],
        scores: Sequence[PageScore],
        aggregates: Sequence[ProbeAggregate],
        top_n: int,
    ) -> TopFlopReport:
        n_probes = scores[0].n_probes if scores else 0
        top_sorted = sorted(scores, key=lambda s: (-s.citation_count, -s.citation_rate, s.url))
        flop_sorted = sorted(scores, key=lambda s: (s.citation_count, s.citation_rate, s.url))
        return TopFlopReport(
            run_id=run_context.run_id,
            target_domain=run_context.target_domain,
            generated_at=self._clock(),
            n_probes=n_probes,
            n_pages=len(pages),
            top=tuple(_to_entries(top_sorted[:top_n])),
            flop=tuple(_to_entries(flop_sorted[:top_n])),
            engine_aggregates=tuple(aggregates),
        )


def _to_entries(scores: Sequence[PageScore]) -> list[TopFlopEntry]:
    return [
        TopFlopEntry(
            position=position,
            url=score.url,
            citation_count=score.citation_count,
            citation_rate=score.citation_rate,
            best_rank=score.best_rank,
        )
        for position, score in enumerate(scores, start=1)
    ]
