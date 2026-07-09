"""Integration: der geschlossene Sprint-4-Loop offline (Fix + Deploy + Re-Probe + Gedaechtnis).

Fuehrt den CrewAI-Sprint-4-Flow mit gemockten Ports aus und prueft: Effekt-Hypothesen entstehen,
werden gespeichert (StoragePort + MemoryPort), das HITL-Gate bleibt hart (Reject => kein Effekt)
und der Offline-Lauf ist bit-reproduzierbar (Seed 42, Effekt im Fingerprint).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.effect import EffectDirection
from geo_audit_loop.domain.fingerprint import report_fingerprint
from geo_audit_loop.domain.fix import DeployStatus
from geo_audit_loop.domain.memory import MemoryQuery
from geo_audit_loop.domain.run import RunStatus
from geo_audit_loop.memory.mock import MockMemoryAdapter
from geo_audit_loop.orchestration.approval import RejectAllGate
from geo_audit_loop.orchestration.factory import RunAssembly, assemble_run
from geo_audit_loop.orchestration.sprint4_flow import Sprint4Pipeline
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _assembly(tmp_path: Path, *, run_id: str = "it-s4", reject: bool = False) -> RunAssembly:
    settings = Settings(
        db_path=tmp_path / "geo.db", max_probes=1000, n_proxy_ips=5, top_n=5, run_seed=42
    )
    version, prompts = load_probe_set("v1")
    return assemble_run(
        settings,
        domain="it-sicherheit.de",
        offline=True,
        run_id=run_id,
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
        learn=True,  # impliziert fix + explain
        approval_gate=RejectAllGate() if reject else None,
    )


def test_sprint4_closes_the_loop(tmp_path: Path) -> None:
    assembly = _assembly(tmp_path)
    assembly.flow.kickoff()

    pipeline = assembly.pipeline
    assert isinstance(pipeline, Sprint4Pipeline)
    # Deploy bleibt sicherer Dry-Run.
    assert pipeline.deploy_result is not None
    assert pipeline.deploy_result.dry_run is True
    assert pipeline.deploy_result.status is DeployStatus.DRY_RUN
    # Live-Loop-Delegation: offline gibt es weder Index-Einreichung noch Overlap-Report.
    assert pipeline.index_result is None
    assert pipeline.overlap_report is None
    assert assembly.storage.load_index_submission("it-s4") is None

    effect = pipeline.effect_report
    assert effect is not None
    assert effect.hypotheses  # je angewandtem Patch eine Hypothese
    # Offline-Boost: jede angewandte, gepatchte URL zeigt einen positiven Effekt.
    assert all(h.delta >= 0 for h in effect.hypotheses)
    assert all(h.direction is EffectDirection.IMPROVED for h in effect.hypotheses)
    assert effect.n_improved == len(effect.hypotheses)

    # Persistenz: EffectReport im StoragePort ...
    assert assembly.storage.load_effect_report("it-s4") == effect
    # ... und die Hypothesen im Gedaechtnis (eigene Tabelle) fuer kuenftige Laeufe.
    con = sqlite3.connect(str(tmp_path / "geo.db"))
    n_hyp = con.execute("SELECT COUNT(*) FROM effect_hypotheses").fetchone()[0]
    # Baseline- UND Re-Probe-Phase liegen unter derselben run_id nebeneinander vor.
    phases = {row[0] for row in con.execute("SELECT DISTINCT phase FROM probes")}
    con.close()
    assert n_hyp == len(effect.hypotheses)
    assert phases == {"baseline", "reprobe"}

    run = assembly.storage.load_run("it-s4")
    assembly.storage.close()
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    # Budget deckt beide Matrizen (Baseline + Re-Probe).
    assert run.total_probes > 0


def test_sprint4_hitl_reject_yields_no_effect(tmp_path: Path) -> None:
    # Harte HITL-Invariante (§6): ohne Freigabe wird nichts angewandt, nichts re-geprobt,
    # nichts gelernt — der Deploy bleibt Dry-Run, das Gedaechtnis bleibt leer.
    assembly = _assembly(tmp_path, reject=True)
    assembly.flow.kickoff()
    pipeline = assembly.pipeline
    assert isinstance(pipeline, Sprint4Pipeline)

    deploy = pipeline.deploy_result
    assert deploy is not None
    assert deploy.dry_run is True
    assert deploy.applied_patch_ids == ()  # nichts freigegeben -> nichts angewandt

    effect = pipeline.effect_report
    assert effect is not None
    assert effect.hypotheses == ()  # kein Effekt gelernt

    memory = MockMemoryAdapter(tmp_path / "geo.db")
    recalled = memory.retrieve(MemoryQuery(target_domain="it-sicherheit.de"))
    memory.close()
    assembly.storage.close()
    assert recalled == []  # Gedaechtnis bleibt leer

    con = sqlite3.connect(str(tmp_path / "geo.db"))
    phases = {row[0] for row in con.execute("SELECT DISTINCT phase FROM probes")}
    con.close()
    assert phases == {"baseline"}  # keine Re-Probe-Phase


def test_sprint4_is_reproducible(tmp_path: Path) -> None:
    def _run(db_dir: Path) -> str:
        db_dir.mkdir()
        assembly = _assembly(db_dir, run_id="rep")
        assembly.pipeline.run()
        pipeline = assembly.pipeline
        assert isinstance(pipeline, Sprint4Pipeline)
        fingerprint = report_fingerprint(
            pipeline.report,  # type: ignore[arg-type]
            pipeline.pattern_report,
            pipeline.audit_report,
            pipeline.fix_plan,
            pipeline.effect_report,
        )
        assembly.storage.close()
        return fingerprint

    # Frische DB, leeres Gedaechtnis -> gleicher Seed liefert denselben Fingerprint (inkl. Effekt).
    assert _run(tmp_path / "a") == _run(tmp_path / "b")
