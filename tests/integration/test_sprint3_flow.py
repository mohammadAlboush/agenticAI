"""Integration: kompletter Sprint-3-Flow offline (Lernen + Fix + HITL + Deploy), reproduzierbar.

Fuehrt den CrewAI-Flow ueber alle sieben Schritte mit gemockten Ports aus und prueft Fix-Plan,
Freigaben, das Dry-Run-Deploy-Ergebnis und den Determinismus (Seed 42). Live-Loop: der
``IndexingPort`` wird offline strukturell NIE aufgerufen (Dry-Run-Deploy => keine Submission);
erst ein echter ``APPLIED``-Deploy ohne Dry-Run loest genau EINE Einreichung aus.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.fix import ApprovalDecision, DeployResult, DeployStatus, FixPlan
from geo_audit_loop.domain.indexing import (
    IndexSubmission,
    IndexSubmissionResult,
    IndexSubmissionStatus,
)
from geo_audit_loop.domain.run import RunContext, RunStatus
from geo_audit_loop.orchestration.factory import RunAssembly, assemble_run
from geo_audit_loop.orchestration.sprint3_flow import Sprint3Pipeline
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)


class SpyIndexingAdapter:
    """``IndexingPort``-Spy: zaehlt Submissions und liefert ein deterministisches Ergebnis."""

    name = "spy"

    def __init__(self) -> None:
        self.submissions: list[IndexSubmission] = []

    def submit(
        self, submission: IndexSubmission, *, run_context: RunContext
    ) -> IndexSubmissionResult:
        self.submissions.append(submission)
        return IndexSubmissionResult(
            run_id=submission.run_id,
            host=submission.host,
            urls=submission.urls,
            generated_at=FIXED,
            dry_run=False,
            status=IndexSubmissionStatus.SUBMITTED,
            detail="spy",
        )


class FakeAppliedPublisher:
    """``PublisherPort``-Fake: simuliert einen ECHTEN Deploy (APPLIED, non-dry-run)."""

    name = "fake-wordpress"

    def publish(
        self,
        plan: FixPlan,
        decisions: Mapping[str, ApprovalDecision],
        *,
        run_context: RunContext,
        dry_run: bool = True,
    ) -> DeployResult:
        applied = tuple(
            p.patch_id
            for p in plan.proposals
            if (d := decisions.get(p.patch_id)) is not None and d.approved
        )
        skipped = tuple(p.patch_id for p in plan.proposals if p.patch_id not in set(applied))
        return DeployResult(
            run_id=run_context.run_id,
            # www-Praefix absichtlich: build_index_submission muss ihn zum Host normalisieren.
            target_domain=f"www.{run_context.target_domain}",
            generated_at=FIXED,
            publisher=self.name,
            dry_run=False,
            applied_patch_ids=applied,
            skipped_patch_ids=skipped,
            status=DeployStatus.APPLIED,
        )


def _assembly(tmp_path: Path, run_id: str = "it-s3") -> RunAssembly:
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
        fix=True,  # impliziert explain
    )


def test_sprint3_flow_offline_proposes_and_deploys(tmp_path: Path) -> None:
    assembly = _assembly(tmp_path)
    assembly.flow.kickoff()

    pipeline = assembly.pipeline
    assert isinstance(pipeline, Sprint3Pipeline)
    assert pipeline.report is not None
    assert pipeline.pattern_report is not None
    assert pipeline.audit_report is not None

    plan = pipeline.fix_plan
    assert plan is not None
    assert plan.proposals  # Patches abgeleitet

    deploy = pipeline.deploy_result
    assert deploy is not None
    assert deploy.dry_run is True
    assert deploy.status is DeployStatus.DRY_RUN
    # AutoApprove => alle Patches freigegeben, keiner uebersprungen
    assert set(deploy.applied_patch_ids) == {p.patch_id for p in plan.proposals}
    assert deploy.skipped_patch_ids == ()

    # Persistenz der Sprint-3-Artefakte
    assert assembly.storage.load_fix_plan("it-s3") is not None
    assert assembly.storage.load_deploy_result("it-s3") is not None
    assert len(assembly.storage.load_approvals("it-s3")) == len(plan.proposals)
    run = assembly.storage.load_run("it-s3")
    assembly.storage.close()
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    assert run.total_tokens > 0

    con = sqlite3.connect(str(tmp_path / "geo.db"))
    n_log = con.execute(
        "SELECT COUNT(*) FROM reasoning_log WHERE run_id = ?", ("it-s3",)
    ).fetchone()[0]
    con.close()
    assert n_log >= 3  # Pattern-Miner + GEO-Auditor + Fix-Agent


def test_offline_dry_run_never_calls_indexer(tmp_path: Path) -> None:
    # Offline-Invariante (Live-Loop): der Deploy bleibt Dry-Run, build_index_submission
    # liefert None -> der IndexingPort wird NIE aufgerufen, nichts wird persistiert.
    assembly = _assembly(tmp_path, run_id="it-s3-noidx")
    pipeline = assembly.pipeline
    assert isinstance(pipeline, Sprint3Pipeline)
    spy = SpyIndexingAdapter()
    pipeline._indexer = spy
    pipeline.run()
    assembly.storage.close()
    assert spy.submissions == []
    assert pipeline.index_result is None
    assert assembly.storage.load_index_submission("it-s3-noidx") is None


def test_applied_non_dry_run_submits_deduplicated_urls_exactly_once(tmp_path: Path) -> None:
    assembly = _assembly(tmp_path, run_id="it-s3-idx")
    pipeline = assembly.pipeline
    assert isinstance(pipeline, Sprint3Pipeline)
    spy = SpyIndexingAdapter()
    pipeline._publisher = FakeAppliedPublisher()
    pipeline._indexer = spy
    pipeline._deploy_dry_run = False  # simuliert das Doppel-Gate (GEO_ALLOW_REMOTE + CLI)
    pipeline.run()

    plan = pipeline.fix_plan
    assert plan is not None
    assert len(spy.submissions) == 1  # genau EINE Einreichung pro Deploy
    submission = spy.submissions[0]
    assert submission.host == "it-sicherheit.de"  # www.-Praefix normalisiert
    # URLs: dedupliziert + aufsteigend sortiert, exakt die der angewandten Patches.
    expected = sorted({p.target_url.strip() for p in plan.proposals})  # AutoApprove: alle
    assert list(submission.urls) == expected

    persisted = assembly.storage.load_index_submission("it-s3-idx")
    assembly.storage.close()
    assert persisted is not None
    assert persisted == pipeline.index_result
    assert persisted.status is IndexSubmissionStatus.SUBMITTED
    assert persisted.dry_run is False


def test_sprint3_is_reproducible(tmp_path: Path) -> None:
    def _run(db_dir: Path) -> tuple[int, int, str]:
        db_dir.mkdir()
        assembly = _assembly(db_dir)
        assembly.pipeline.run()
        pipeline = assembly.pipeline
        assert isinstance(pipeline, Sprint3Pipeline)
        plan = pipeline.fix_plan
        deploy = pipeline.deploy_result
        assembly.storage.close()
        assert plan is not None
        assert deploy is not None
        return len(plan.proposals), len(deploy.applied_patch_ids), plan.proposals[0].patch_id

    assert _run(tmp_path / "a") == _run(tmp_path / "b")
