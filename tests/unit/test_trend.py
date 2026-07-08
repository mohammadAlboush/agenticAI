"""Unit: Zitations-Trend — reine, deterministische Domaenenfunktion (Session 7)."""

from __future__ import annotations

from datetime import datetime, timedelta

from geo_audit_loop.domain.trend import (
    TrendDirection,
    TrendPoint,
    TrendReport,
    compute_trend,
)

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _point(run_id: str, rate: float, *, day: int = 0, n: int = 48) -> TrendPoint:
    return TrendPoint(
        run_id=run_id,
        observed_at=FIXED + timedelta(days=day),
        overall_citation_rate=rate,
        n_probes=n,
    )


def _trend(points: list[TrendPoint], *, threshold: float = 0.10) -> TrendReport:
    return compute_trend(
        points, target_domain="it-sicherheit.de", generated_at=FIXED, drift_threshold=threshold
    )


def test_empty_history() -> None:
    report = _trend([])
    assert report.n_runs == 0
    assert report.latest is None
    assert report.baseline is None
    assert report.delta == 0.0
    assert report.direction is TrendDirection.STABLE
    assert report.mean_rate == 0.0
    assert report.alert is False


def test_single_run_is_stable() -> None:
    report = _trend([_point("r1", 0.5)])
    assert report.n_runs == 1
    assert report.latest is not None and report.latest.run_id == "r1"
    assert report.baseline is None
    assert report.delta == 0.0
    assert report.direction is TrendDirection.STABLE
    assert report.mean_rate == 0.5


def test_regression_over_threshold_triggers_alert() -> None:
    report = _trend([_point("r1", 0.60, day=0), _point("r2", 0.40, day=1)], threshold=0.10)
    assert report.direction is TrendDirection.REGRESSED
    assert report.delta == -0.2
    assert report.alert is True  # 0.20 >= 0.10


def test_small_regression_below_threshold_no_alert() -> None:
    report = _trend([_point("r1", 0.50, day=0), _point("r2", 0.45, day=1)], threshold=0.10)
    assert report.direction is TrendDirection.REGRESSED  # 0.05 > epsilon 0.01
    assert report.alert is False  # 0.05 < 0.10


def test_improvement_never_alerts() -> None:
    report = _trend([_point("r1", 0.30, day=0), _point("r2", 0.80, day=1)], threshold=0.10)
    assert report.direction is TrendDirection.IMPROVED
    assert report.delta == 0.5
    assert report.alert is False


def test_within_epsilon_is_stable() -> None:
    report = _trend([_point("r1", 0.500, day=0), _point("r2", 0.505, day=1)])
    assert report.direction is TrendDirection.STABLE  # 0.005 < epsilon 0.01
    assert report.alert is False


def test_sorts_chronologically_regardless_of_input_order() -> None:
    # Neuester Punkt (day=2) als letzter Vergleichswert, egal in welcher Reihenfolge uebergeben.
    points = [_point("r3", 0.20, day=2), _point("r1", 0.90, day=0), _point("r2", 0.50, day=1)]
    report = _trend(points)
    assert [p.run_id for p in report.points] == ["r1", "r2", "r3"]
    assert report.latest is not None and report.latest.run_id == "r3"
    assert report.baseline is not None and report.baseline.run_id == "r2"
    assert report.delta == -0.3  # 0.20 - 0.50


def test_mean_rate_rounded() -> None:
    report = _trend([_point("r1", 1.0, day=0), _point("r2", 0.0, day=1), _point("r3", 0.0, day=2)])
    assert report.mean_rate == round(1 / 3, 6)


def test_determinism_same_inputs_same_report() -> None:
    points = [_point("r1", 0.6, day=0), _point("r2", 0.4, day=1)]
    assert _trend(points) == _trend(points)
