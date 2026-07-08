"""Integration: das harte Human-in-the-Loop-Gate (Projektregeln §6).

Beweist in Code: (1) ``apply_patches`` ohne vorherige Freigabe wirft ``DeployBlocked`` und
hinterlaesst KEIN Deploy-Ergebnis; (2) bei Ablehnung aller Patches wird nichts angewandt und
der ``FilesystemPublisher`` schreibt NULL Dateien. Kein Deploy ohne Freigabe.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.errors import DeployBlocked
from geo_audit_loop.domain.fix import DeployStatus
from geo_audit_loop.orchestration.approval import RejectAllGate
from geo_audit_loop.orchestration.factory import RunAssembly, assemble_run
from geo_audit_loop.orchestration.sprint3_flow import Sprint3Pipeline
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _assembly(tmp_path: Path, **gate_kwargs: object) -> RunAssembly:
    settings = Settings(
        db_path=tmp_path / "geo.db",
        runs_dir=tmp_path / "runs",
        publisher="filesystem",
        max_probes=1000,
        n_proxy_ips=5,
        top_n=5,
        run_seed=42,
    )
    version, prompts = load_probe_set("v1")
    return assemble_run(
        settings,
        domain="it-sicherheit.de",
        offline=True,
        run_id="hitl",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
        fix=True,
        **gate_kwargs,  # type: ignore[arg-type]
    )


def test_apply_without_approval_is_blocked(tmp_path: Path) -> None:
    assembly = _assembly(tmp_path)
    pipeline = assembly.pipeline
    assert isinstance(pipeline, Sprint3Pipeline)
    pipeline.sample()
    pipeline.crawl_and_report()
    pipeline.mine_patterns()
    pipeline.audit_flops()
    pipeline.propose_fixes()
    # Freigabe-Schritt BEWUSST uebersprungen -> Deploy muss hart blockieren:
    with pytest.raises(DeployBlocked):
        pipeline.apply_patches()
    assembly.storage.close()
    assert assembly.storage.load_deploy_result("hitl") is None  # kein Deploy-Ergebnis
    assert not (tmp_path / "runs" / "hitl").exists()  # kein Artefakt geschrieben


def test_reject_all_applies_nothing_and_writes_no_files(tmp_path: Path) -> None:
    assembly = _assembly(tmp_path, approval_gate=RejectAllGate())
    assembly.pipeline.run()
    pipeline = assembly.pipeline
    assert isinstance(pipeline, Sprint3Pipeline)
    plan = pipeline.fix_plan
    deploy = pipeline.deploy_result
    assert plan is not None
    assert deploy is not None
    assert deploy.applied_patch_ids == ()  # nichts angewandt
    assert set(deploy.skipped_patch_ids) == {p.patch_id for p in plan.proposals}
    assert deploy.status is DeployStatus.DRY_RUN
    assembly.storage.close()
    # FilesystemPublisher hat NULL Dateien geschrieben (kein patches/-Ordner):
    assert not (tmp_path / "runs" / "hitl" / "patches").exists()
