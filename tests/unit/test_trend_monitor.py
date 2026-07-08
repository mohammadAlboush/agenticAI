"""Unit: Trend-Monitor liest die Lauf-Historie aus dem Storage und baut den Trend (Session 7)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
from geo_audit_loop.agents.trend_monitor import TrendMonitorService
from geo_audit_loop.domain.probe import EngineId, ProbePhase, ProbeResult, ProbeStatus
from geo_audit_loop.domain.run import RunRecord, RunStatus
from geo_audit_loop.domain.trend import TrendDirection

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _storage(tmp_path: Path) -> SqliteStorage:
    storage = SqliteStorage(tmp_path / "geo.db")
    storage.initialize()
    return storage


def _run(
    run_id: str, domain: str, *, day: int, status: RunStatus = RunStatus.COMPLETED
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        target_domain=domain,
        status=status,
        started_at=FIXED + timedelta(days=day),
        seed=42,
        prompt_set_version="v1",
        config_hash="hash",
    )


def _probe(run_id: str, prompt_id: str, *, cited: bool) -> ProbeResult:
    return ProbeResult(
        run_id=run_id,
        engine_id=EngineId.PERPLEXITY,
        model="m",
        prompt_id=prompt_id,
        prompt_version="v1",
        proxy_label="proxy-0",
        target_cited=cited,
        status=ProbeStatus.OK,
        probed_at=FIXED,
        phase=ProbePhase.BASELINE,
    )


def _save_run(storage: SqliteStorage, run: RunRecord, *cited: bool) -> None:
    storage.save_run(run)
    for i, hit in enumerate(cited):
        storage.save_probe(_probe(run.run_id, f"p{i}", cited=hit))


def test_trend_from_history_flags_regression(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    # Domain a.de: frueher hohe Zitationsrate (1.0), spaeter niedrige (0.0) -> Regression.
    _save_run(storage, _run("a1", "a.de", day=0), True, True, True, True)
    _save_run(storage, _run("a2", "a.de", day=1), False, False, False, False)
    # Fremde Domain + laufender (nicht abgeschlossener) Lauf duerfen nicht einfliessen.
    _save_run(storage, _run("b1", "b.de", day=0), True, True)
    _save_run(storage, _run("a3", "a.de", day=2, status=RunStatus.RUNNING), True, True)

    report = TrendMonitorService(storage=storage, clock=lambda: FIXED).run(
        "a.de", drift_threshold=0.10
    )
    storage.close()

    assert report.n_runs == 2  # nur die zwei abgeschlossenen a.de-Laeufe
    assert [p.run_id for p in report.points] == ["a1", "a2"]  # chronologisch
    assert report.latest is not None and report.latest.overall_citation_rate == 0.0
    assert report.baseline is not None and report.baseline.overall_citation_rate == 1.0
    assert report.delta == -1.0
    assert report.direction is TrendDirection.REGRESSED
    assert report.alert is True


def test_trend_empty_for_unknown_domain(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _save_run(storage, _run("a1", "a.de", day=0), True)
    report = TrendMonitorService(storage=storage, clock=lambda: FIXED).run("unknown.de")
    storage.close()
    assert report.n_runs == 0
    assert report.alert is False


def test_rate_ignores_error_probes(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    run = _run("a1", "a.de", day=0)
    storage.save_run(run)
    storage.save_probe(_probe("a1", "p0", cited=True))
    # Eine ERROR-Probe zaehlt nicht in den Nenner.
    err = _probe("a1", "p1", cited=True).model_copy(update={"status": ProbeStatus.ERROR})
    storage.save_probe(err)
    report = TrendMonitorService(storage=storage, clock=lambda: FIXED).run("a.de")
    storage.close()
    assert report.latest is not None
    assert report.latest.overall_citation_rate == 1.0  # 1 von 1 OK-Probe
    assert report.latest.n_probes == 1
