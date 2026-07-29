"""Integration: das harte Human-in-the-Loop-Gate (Projektregeln §6).

Beweist in Code: (1) ``apply_patches`` ohne vorherige Freigabe wirft ``DeployBlocked`` und
hinterlaesst KEIN Deploy-Ergebnis; (2) bei Ablehnung aller Patches wird nichts angewandt und
der ``FilesystemPublisher`` schreibt NULL Dateien; (3) ``--approve-all`` (AutoApproveGate)
kann NIE einen echten Remote-Deploy freischalten (``ConfigError`` in der Factory);
(4) ``--offline`` verdrahtet nie den WordPress-Publisher (kein Netz im Offline-Pfad).
Kein Deploy ohne Freigabe.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from geo_audit_loop.adapters.publisher.mock import MockPublisher
from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.errors import ConfigError, DeployBlocked
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
    # Kein Deploy => strukturell auch keine Index-Einreichung (Live-Loop-Kette bleibt zu).
    assert pipeline.index_result is None
    assert assembly.storage.load_index_submission("hitl") is None


def test_auto_approve_gate_cannot_enable_real_remote_deploy(tmp_path: Path) -> None:
    """--approve-all + --allow-remote + GEO_ALLOW_REMOTE darf NIE real deployen (§6)."""
    settings = Settings(
        db_path=tmp_path / "geo.db",
        runs_dir=tmp_path / "runs",
        publisher="filesystem",
        allow_remote=True,  # Env-Haelfte des Doppel-Gates
        proxy_file=None,
        max_probes=1000,
        n_proxy_ips=5,
        top_n=5,
        run_seed=42,
    )
    version, prompts = load_probe_set("v1")
    with pytest.raises(ConfigError):
        assemble_run(
            settings,
            domain="it-sicherheit.de",
            offline=False,  # nur live kann deploy_dry_run=False ueberhaupt entstehen
            run_id="hitl-auto",
            now=FIXED,
            prompts=prompts,
            prompt_version=version,
            fix=True,
            allow_remote=True,  # CLI-Haelfte des Doppel-Gates
            # approval_gate=None -> Factory-Default AutoApproveGate => ConfigError.
        )


def test_non_auto_gate_allows_remote_wiring(tmp_path: Path) -> None:
    """Gegenprobe: mit explizitem (nicht-automatischem) Gate blockiert die Factory nicht."""
    settings = Settings(
        db_path=tmp_path / "geo.db",
        runs_dir=tmp_path / "runs",
        publisher="filesystem",
        allow_remote=True,
        proxy_file=None,
        max_probes=1000,
        n_proxy_ips=5,
        top_n=5,
        run_seed=42,
    )
    version, prompts = load_probe_set("v1")
    assembly = assemble_run(
        settings,
        domain="it-sicherheit.de",
        offline=False,
        run_id="hitl-human",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
        fix=True,
        allow_remote=True,
        approval_gate=RejectAllGate(),  # Stellvertreter einer menschlichen Entscheidung
    )
    assert isinstance(assembly.pipeline, Sprint3Pipeline)
    assembly.storage.close()


def test_offline_run_never_wires_wordpress_publisher(tmp_path: Path) -> None:
    """Live-vorbereitete .env (wordpress + Gates + Creds) macht --offline trotzdem hermetisch."""
    settings = Settings(
        db_path=tmp_path / "geo.db",
        runs_dir=tmp_path / "runs",
        publisher="wordpress",
        allow_remote=True,
        wp_base_url="https://site.example",
        wp_username="admin",
        wp_app_password="app-pass-geheim",
        max_probes=1000,
        n_proxy_ips=5,
        top_n=5,
        run_seed=42,
    )
    version, prompts = load_probe_set("v1")
    assembly = assemble_run(
        settings,
        domain="it-sicherheit.de",
        offline=True,
        run_id="hitl-offline",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
        fix=True,
        approval_gate=RejectAllGate(),
    )
    pipeline = assembly.pipeline
    assert isinstance(pipeline, Sprint3Pipeline)
    # Kein WordPressPublisher im Offline-Pfad: schon der Dry-Run wuerde Slug-Resolve-GETs
    # gegen die Live-Site machen (Netz-I/O) — offline erzwingt den MockPublisher.
    assert isinstance(pipeline._publisher, MockPublisher)
    assembly.storage.close()


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
    # Keine Freigabe => kein Apply => kein IndexNow (build_index_submission-Gate greift).
    assert pipeline.index_result is None
    assert assembly.storage.load_index_submission("hitl") is None
