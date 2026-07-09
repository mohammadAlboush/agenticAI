"""Unit: Publisher-Adapter — HITL-Filter, Dry-Run-Sicherheit, keine externen Writes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from geo_audit_loop.adapters.publisher.filesystem import FilesystemPublisher
from geo_audit_loop.adapters.publisher.mock import MockPublisher
from geo_audit_loop.adapters.publisher.stub_remote import GitHubPublisher
from geo_audit_loop.domain.errors import DeployBlocked
from geo_audit_loop.domain.fix import (
    ApprovalDecision,
    ChangeType,
    DeployStatus,
    FixPlan,
    FixProposal,
)
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.domain.run import RunContext

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _clock() -> datetime:
    return FIXED


def _proposal(patch_id: str, finding_id: str) -> FixProposal:
    return FixProposal(
        patch_id=patch_id,
        finding_id=finding_id,
        target_url=f"https://www.it-sicherheit.de/{finding_id}",
        lever=Lever.ANSWER_BLOCKS,
        pyramid_level=PyramidLevel.EXTRACTABILITY,
        change_type=ChangeType.INSERT_BLOCK,
        proposed_content="Praegnanter Antwortblock (40-60 Woerter).",
        rationale="Template t1 verlangt einen extrahierbaren Antwortblock.",
        confidence=0.8,
    )


def _plan() -> FixPlan:
    return FixPlan(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        prompt_version="v1",
        proposals=(_proposal("px-a", "f1"), _proposal("px-b", "f2"), _proposal("px-c", "f3")),
    )


def _decision(patch_id: str, approved: bool) -> ApprovalDecision:
    return ApprovalDecision(
        patch_id=patch_id, run_id="run-1", approved=approved, reviewer="test", decided_at=FIXED
    )


def _ctx() -> RunContext:
    return RunContext(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        started_at=FIXED,
        seed=42,
        prompt_set_version="v1",
        config_hash="abc",
    )


def test_mock_applies_only_approved() -> None:
    decisions = {"px-a": _decision("px-a", True), "px-b": _decision("px-b", False)}
    # px-c hat GAR KEINE Entscheidung -> muss uebersprungen werden (HITL-Gate).
    result = MockPublisher(clock=_clock).publish(_plan(), decisions, run_context=_ctx())
    assert result.dry_run is True
    assert result.status is DeployStatus.DRY_RUN
    assert result.applied_patch_ids == ("px-a",)
    assert set(result.skipped_patch_ids) == {"px-b", "px-c"}


def test_mock_no_decisions_applies_nothing() -> None:
    result = MockPublisher(clock=_clock).publish(_plan(), {}, run_context=_ctx())
    assert result.applied_patch_ids == ()
    assert len(result.skipped_patch_ids) == 3


def test_filesystem_writes_only_approved(tmp_path: Path) -> None:
    decisions = {"px-a": _decision("px-a", True), "px-b": _decision("px-b", False)}
    pub = FilesystemPublisher(tmp_path, clock=_clock)
    result = pub.publish(_plan(), decisions, run_context=_ctx())
    patches_dir = tmp_path / "run-1" / "patches"
    assert (patches_dir / "px-a.json").exists()
    assert not (patches_dir / "px-b.json").exists()  # abgelehnt -> nichts geschrieben
    assert (patches_dir / "fix_plan.json").exists()
    assert result.status is DeployStatus.APPLIED
    assert result.artifact_path == str(patches_dir)
    assert result.dry_run is True  # Live-Domain unberuehrt


def test_filesystem_no_approval_writes_zero_files(tmp_path: Path) -> None:
    pub = FilesystemPublisher(tmp_path, clock=_clock)
    result = pub.publish(_plan(), {}, run_context=_ctx())
    assert not (tmp_path / "run-1").exists()  # KEINE Datei angelegt
    assert result.applied_patch_ids == ()
    assert result.status is DeployStatus.DRY_RUN


def test_remote_stub_blocks_by_default() -> None:
    decisions = {"px-a": _decision("px-a", True)}
    with pytest.raises(DeployBlocked):
        GitHubPublisher(clock=_clock).publish(_plan(), decisions, run_context=_ctx())


def test_remote_stub_with_flag_still_applies_nothing() -> None:
    decisions = {"px-a": _decision("px-a", True)}
    result = GitHubPublisher(allow_remote=True, clock=_clock).publish(
        _plan(), decisions, run_context=_ctx()
    )
    assert result.status is DeployStatus.BLOCKED
    assert result.applied_patch_ids == ()
