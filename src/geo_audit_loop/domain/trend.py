"""Trend-/Monitoring-Contracts (Session 7): Zitations-Sichtbarkeit ueber die Lauf-Historie.

Macht aus Einzel-Laeufen ein **Fruehwarnsystem**: je Domain wird die Gesamt-Zitationsrate
ueber die Zeit als Reihe gefuehrt und der letzte Lauf gegen den vorherigen verglichen. Ein
signifikanter Rueckgang loest einen **Drift-Alert** aus („diese Woche Zitier-Anteil verloren").
Diese **reine, deterministische** Domaenenfunktion (kein LLM/RNG) rechnet nur auf den bereits
gemessenen Raten -> bit-reproduzierbar (Projektregeln §7). Der erste Slice nutzt eine
dokumentierte Delta-Schwelle; die KI-basierte Signifikanz (Konfidenz-Intervall-Trennung ueber
die Zeit) ist der klar abgegrenzte Folgeschritt, sobald die Wilson-KIs verfuegbar sind.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from statistics import fmean
from typing import Final

from pydantic import Field

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain._base import FrozenModel


class TrendDirection(StrEnum):
    """Richtung des Zitier-Anteils vom vorherigen zum letzten Lauf."""

    IMPROVED = "improved"  # Anteil gestiegen (ueber Epsilon)
    REGRESSED = "regressed"  # Anteil gesunken (ueber Epsilon)
    STABLE = "stable"  # unveraendert / zu wenige Laeufe


class TrendPoint(FrozenModel):
    """Ein Punkt der Zeitreihe: die Gesamt-Zitationsrate eines abgeschlossenen Laufs."""

    run_id: str = Field(min_length=1)
    observed_at: datetime
    overall_citation_rate: float = Field(ge=0.0, le=1.0)  # Anteil zitierter OK-Baseline-Probes
    n_probes: int = Field(ge=0)


class TrendReport(FrozenModel):
    """Zitations-Trend einer Domain ueber ihre Lauf-Historie + Drift-Alert.

    Deterministisches Read-Artefakt (aus bereits gemessenen Laeufen); kein neuer Probe-/
    Engine-Aufruf. ``alert`` ist wahr, wenn der letzte Lauf gegenueber dem vorherigen um
    mindestens ``drift_threshold`` an Zitier-Anteil verloren hat.
    """

    target_domain: str = Field(min_length=1)
    generated_at: datetime
    n_runs: int = Field(ge=0)
    points: tuple[TrendPoint, ...] = ()  # chronologisch (aeltester zuerst)
    latest: TrendPoint | None = None
    baseline: TrendPoint | None = None  # der unmittelbar vorherige Lauf
    delta: float = Field(default=0.0, ge=-1.0, le=1.0)  # latest - baseline (0 bei < 2 Laeufen)
    direction: TrendDirection = TrendDirection.STABLE
    mean_rate: float = Field(default=0.0, ge=0.0, le=1.0)  # Mittel ueber alle Laeufe
    drift_threshold: float = Field(ge=0.0, le=1.0)  # verwendete Schwelle (Transparenz)
    alert: bool = False


def classify_trend(delta: float, *, epsilon: float) -> TrendDirection:
    """Bildet ein (gerundetes) Delta auf eine Richtung ab (STABIL innerhalb Epsilon)."""
    if abs(delta) < epsilon:
        return TrendDirection.STABLE
    return TrendDirection.IMPROVED if delta > 0 else TrendDirection.REGRESSED


def compute_trend(
    points: Sequence[TrendPoint],
    *,
    target_domain: str,
    generated_at: datetime,
    drift_threshold: float = c.TREND_DRIFT_THRESHOLD,
    epsilon: float = c.TREND_DIRECTION_EPSILON,
) -> TrendReport:
    """Bildet aus den Zeitreihen-Punkten den Trend + Drift-Alert (reine Funktion).

    Sortiert chronologisch (``observed_at``, dann ``run_id`` als totaler Ordnungsschluessel);
    vergleicht den letzten Lauf mit dem vorherigen. Ein Alert entsteht nur bei einer
    Verschlechterung (Richtung REGRESSED), deren Betrag ``drift_threshold`` erreicht. Raten/
    Deltas werden auf 6 Nachkommastellen gerundet (Bit-Reproduzierbarkeit).

    Args:
        points: Die Zeitreihen-Punkte (Reihenfolge egal; ``observed_at`` muss tz-konsistent sein).
        target_domain: Die ueberwachte Domain.
        generated_at: Zeitstempel (injizierte Uhr).
        drift_threshold: Rueckgang der Zitationsrate, ab dem der Alert feuert.
        epsilon: Mindestbetrag, ab dem ein Delta ueberhaupt eine Richtung hat.

    Returns:
        Einen ``TrendReport`` mit chronologischer Reihe, letztem/vorherigem Punkt, Delta,
        Richtung, Mittelwert und Drift-Alert.
    """
    ordered = tuple(sorted(points, key=lambda p: (p.observed_at, p.run_id)))
    n = len(ordered)
    latest = ordered[-1] if n >= 1 else None
    baseline = ordered[-2] if n >= 2 else None
    if latest is not None and baseline is not None:
        delta = round(latest.overall_citation_rate - baseline.overall_citation_rate, 6)
    else:
        delta = 0.0
    direction = classify_trend(delta, epsilon=epsilon)
    mean_rate = round(fmean(p.overall_citation_rate for p in ordered), 6) if ordered else 0.0
    alert = direction is TrendDirection.REGRESSED and abs(delta) >= drift_threshold
    return TrendReport(
        target_domain=target_domain,
        generated_at=generated_at,
        n_runs=n,
        points=ordered,
        latest=latest,
        baseline=baseline,
        delta=delta,
        direction=direction,
        mean_rate=mean_rate,
        drift_threshold=drift_threshold,
        alert=alert,
    )


#: Etiketten der Trend-Richtungen fuer die Praesentationsschicht (keine Magic Strings).
TREND_DIRECTION_LABELS: Final[dict[TrendDirection, str]] = {
    TrendDirection.IMPROVED: "gestiegen",
    TrendDirection.REGRESSED: "gesunken",
    TrendDirection.STABLE: "stabil",
}
