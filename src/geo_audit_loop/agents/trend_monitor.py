"""Trend-Monitor-Service (Session 7): baut aus der Lauf-Historie den Zitations-Trend.

Liest die abgeschlossenen Laeufe einer Domain ueber den ``StoragePort``, berechnet je Lauf die
Gesamt-Zitationsrate aus den OK-Baseline-Probes und uebergibt die Zeitreihe an die reine
``compute_trend``-Domaenenfunktion. Kein neuer Probe-/Engine-Aufruf — reine Auswertung des
bereits Gemessenen. Haengt nur an domain, ports und observability (Projektregeln §3).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from statistics import fmean
from typing import Final

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain.probe import ProbePhase, ProbeResult, ProbeStatus
from geo_audit_loop.domain.run import RunRecord, RunStatus
from geo_audit_loop.domain.trend import TrendPoint, TrendReport, compute_trend
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.ports.storage import StoragePort

_AGENT: Final = "trend_monitor"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_aware(value: datetime) -> datetime:
    """Naive Zeitstempel als UTC interpretieren (tz-robuster Vergleich, wie im Storage)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _citation_rate(probes: Sequence[ProbeResult]) -> tuple[float, int]:
    """Gesamt-Zitationsrate ueber die OK-Probes eines Laufs + deren Anzahl."""
    ok = [p for p in probes if p.status is ProbeStatus.OK]
    if not ok:
        return 0.0, 0
    return round(fmean(1.0 if p.target_cited else 0.0 for p in ok), 6), len(ok)


class TrendMonitorService:
    """Erzeugt den ``TrendReport`` einer Domain aus ihrer persistierten Lauf-Historie."""

    def __init__(
        self,
        *,
        storage: StoragePort,
        logger: logging.Logger | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._storage = storage
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._clock = clock if clock is not None else _utc_now

    def run(
        self, target_domain: str, *, drift_threshold: float = c.TREND_DRIFT_THRESHOLD
    ) -> TrendReport:
        """Baut den Zitations-Trend der Domain (nur abgeschlossene Laeufe zaehlen)."""
        completed = [
            run
            for run in self._storage.list_runs()
            if run.target_domain == target_domain and run.status is RunStatus.COMPLETED
        ]
        points = [self._point(run) for run in completed]
        report = compute_trend(
            points,
            target_domain=target_domain,
            generated_at=self._clock(),
            drift_threshold=drift_threshold,
        )
        log_event(
            self._log,
            "trend.done",
            run_id="monitor",  # domaenen-, nicht laufbezogen -> festes Korrelations-Token
            agent=_AGENT,
            target_domain=target_domain,
            n_runs=report.n_runs,
            direction=report.direction.value,
            alert=report.alert,
        )
        return report

    def _point(self, run: RunRecord) -> TrendPoint:
        probes = self._storage.load_probes(run.run_id, ProbePhase.BASELINE)
        rate, n = _citation_rate(probes)
        return TrendPoint(
            run_id=run.run_id,
            observed_at=_as_aware(run.started_at),
            overall_citation_rate=rate,
            n_probes=n,
        )
