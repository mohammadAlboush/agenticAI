"""Unit: Indexing-Contracts — hartes APPLIED+non-dry-run-Gate, Dedupe/Sortierung."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from geo_audit_loop.domain.fix import (
    ChangeType,
    DeployResult,
    DeployStatus,
    FixPlan,
    FixProposal,
)
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.domain.indexing import (
    EndpointResult,
    IndexingEndpoint,
    IndexSubmission,
    IndexSubmissionResult,
    IndexSubmissionStatus,
    build_index_submission,
)

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _proposal(patch_id: str, target_url: str) -> FixProposal:
    return FixProposal(
        patch_id=patch_id,
        finding_id="f1",
        target_url=target_url,
        lever=Lever.ANSWER_BLOCKS,
        pyramid_level=PyramidLevel.EXTRACTABILITY,
        change_type=ChangeType.INSERT_BLOCK,
        proposed_content="Block",
        rationale="Antwortblock fehlt.",
        confidence=0.8,
    )


def _plan(*proposals: FixProposal) -> FixPlan:
    return FixPlan(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        prompt_version="v1",
        proposals=tuple(proposals),
    )


def _deploy(
    status: DeployStatus = DeployStatus.APPLIED,
    dry_run: bool = False,
    applied: tuple[str, ...] = ("px-1",),
    target_domain: str = "it-sicherheit.de",
) -> DeployResult:
    return DeployResult(
        run_id="run-1",
        target_domain=target_domain,
        generated_at=FIXED,
        publisher="wordpress",
        dry_run=dry_run,
        applied_patch_ids=applied,
        status=status,
    )


def test_gate_dry_run_yields_none() -> None:
    # Hartes Gate: Dry-Run darf NIE eine Index-Einreichung ausloesen (Offline-Golden-Pfad).
    plan = _plan(_proposal("px-1", "https://it-sicherheit.de/a"))
    assert build_index_submission(plan, _deploy(dry_run=True)) is None


@pytest.mark.parametrize(
    "status", [DeployStatus.DRY_RUN, DeployStatus.BLOCKED, DeployStatus.FAILED]
)
def test_gate_non_applied_status_yields_none(status: DeployStatus) -> None:
    plan = _plan(_proposal("px-1", "https://it-sicherheit.de/a"))
    assert build_index_submission(plan, _deploy(status=status)) is None


def test_gate_no_applied_patches_yields_none() -> None:
    plan = _plan(_proposal("px-1", "https://it-sicherheit.de/a"))
    assert build_index_submission(plan, _deploy(applied=())) is None


def test_build_dedupes_and_sorts_urls() -> None:
    plan = _plan(
        _proposal("px-1", "https://it-sicherheit.de/zzz"),
        _proposal("px-2", "https://it-sicherheit.de/aaa"),
        _proposal("px-3", "https://it-sicherheit.de/zzz"),  # Duplikat derselben Seite
        _proposal("px-4", "https://it-sicherheit.de/nope"),  # NICHT angewandt
    )
    submission = build_index_submission(plan, _deploy(applied=("px-1", "px-2", "px-3")))
    assert submission is not None
    assert submission.urls == (
        "https://it-sicherheit.de/aaa",
        "https://it-sicherheit.de/zzz",
    )
    assert submission.run_id == "run-1"
    assert submission.host == "it-sicherheit.de"
    assert "2" in submission.reason  # Anzahl eingereichter URLs in der Provenienz


def test_build_normalizes_host_www_and_case() -> None:
    plan = _plan(_proposal("px-1", "https://www.Beispiel.de/a"))
    submission = build_index_submission(plan, _deploy(target_domain="WWW.Beispiel.DE"))
    assert submission is not None
    assert submission.host == "beispiel.de"


def test_urls_stay_verbatim_no_normalization() -> None:
    # IndexNow verlangt die publizierte URL — Trailing-Slash/www bleiben unangetastet.
    plan = _plan(_proposal("px-1", "https://www.it-sicherheit.de/a/"))
    submission = build_index_submission(plan, _deploy())
    assert submission is not None
    assert submission.urls == ("https://www.it-sicherheit.de/a/",)


def test_submission_rejects_unsorted_or_duplicate_urls() -> None:
    with pytest.raises(ValidationError):
        IndexSubmission(run_id="r", host="h.de", urls=("b", "a"), reason="x")
    with pytest.raises(ValidationError):
        IndexSubmission(run_id="r", host="h.de", urls=("a", "a"), reason="x")


def test_submission_requires_at_least_one_url() -> None:
    with pytest.raises(ValidationError):
        IndexSubmission(run_id="r", host="h.de", urls=(), reason="x")


def test_result_defaults_are_safe() -> None:
    # Default SICHER: ohne explizites Gegenteil wurde nichts extern gesendet.
    result = IndexSubmissionResult(run_id="r", host="h.de", generated_at=FIXED)
    assert result.dry_run is True
    assert result.status is IndexSubmissionStatus.SKIPPED
    assert result.endpoints == ()


def test_endpoint_result_carries_http_status() -> None:
    endpoint = EndpointResult(
        endpoint=IndexingEndpoint.INDEXNOW,
        status=IndexSubmissionStatus.RATE_LIMITED,
        http_status=429,
        attempts=1,
        detail="429 vom Index — terminal, kein Retry",
    )
    assert endpoint.status is IndexSubmissionStatus.RATE_LIMITED
    assert endpoint.http_status == 429
    assert endpoint.attempts == 1
