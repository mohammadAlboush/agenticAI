"""Unit: Sprint-3-Contracts — FixProposal/FixPlan/ApprovalDecision/DeployResult."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from geo_audit_loop.domain.fix import (
    ApprovalDecision,
    ChangeType,
    DeployResult,
    DeployStatus,
    FixPlan,
    FixProposal,
    FixStatus,
    derive_patch_id,
    prioritize_proposals,
)
from geo_audit_loop.domain.geo import Lever, PyramidLevel

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _proposal(
    patch_id: str = "px-f1-add_schema",
    *,
    change_type: ChangeType = ChangeType.ADD_SCHEMA,
    pyramid_level: PyramidLevel = PyramidLevel.SUBSTANCE,
    confidence: float = 0.8,
    current_excerpt: str = "",
) -> FixProposal:
    return FixProposal(
        patch_id=patch_id,
        finding_id="f1",
        target_url="https://www.it-sicherheit.de/firewall-grundlagen",
        lever=Lever.ENTITY_CLARITY,
        pyramid_level=pyramid_level,
        change_type=change_type,
        current_excerpt=current_excerpt,
        proposed_content='{"@type": "Person", "name": "..."}',
        rationale="Autor-Schema fehlt — Template t2 verlangt Entitaeten-Klarheit.",
        confidence=confidence,
    )


def test_proposal_defaults_and_status() -> None:
    p = _proposal()
    assert p.status is FixStatus.PROPOSED
    assert p.unified_diff == ""
    assert p.template_id is None


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        FixProposal.model_validate({**_proposal().model_dump(), "junk": 1})


def test_rewrite_requires_current_excerpt() -> None:
    with pytest.raises(ValidationError):
        _proposal(change_type=ChangeType.REWRITE_BLOCK, current_excerpt="")
    # mit Auszug ist rewrite_block gueltig:
    ok = _proposal(change_type=ChangeType.REWRITE_BLOCK, current_excerpt="alter Absatz")
    assert ok.change_type is ChangeType.REWRITE_BLOCK


def test_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        _proposal(confidence=1.5)


def test_derive_patch_id_is_deterministic() -> None:
    assert derive_patch_id("f3", ChangeType.INSERT_BLOCK) == "px-f3-insert_block"
    assert derive_patch_id("f3", ChangeType.INSERT_BLOCK) == derive_patch_id(
        "f3", ChangeType.INSERT_BLOCK
    )


def test_prioritize_proposals_by_pyramid_then_confidence() -> None:
    low_pyramid = _proposal("px-a", pyramid_level=PyramidLevel.EXTRACTABILITY, confidence=0.5)
    high_pyramid = _proposal("px-b", pyramid_level=PyramidLevel.CITATION, confidence=0.9)
    same_low_better = _proposal(
        "px-c", pyramid_level=PyramidLevel.EXTRACTABILITY, confidence=0.9
    )
    ordered = prioritize_proposals((high_pyramid, low_pyramid, same_low_better))
    # untere Pyramide zuerst; innerhalb gleicher Ebene hoehere Konfidenz zuerst
    assert [p.patch_id for p in ordered] == ["px-c", "px-a", "px-b"]


def test_fixplan_roundtrip() -> None:
    plan = FixPlan(
        run_id="r1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        prompt_version="v1",
        proposals=(_proposal(),),
    )
    restored = FixPlan.model_validate_json(plan.model_dump_json())
    assert restored == plan


def test_approval_decision_roundtrip() -> None:
    d = ApprovalDecision(
        patch_id="px-f1-add_schema",
        run_id="r1",
        approved=True,
        reviewer="cli:--approve-all",
        decided_at=FIXED,
    )
    assert ApprovalDecision.model_validate_json(d.model_dump_json()) == d


def test_deploy_result_defaults_are_safe() -> None:
    r = DeployResult(
        run_id="r1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        publisher="mock",
    )
    assert r.dry_run is True
    assert r.status is DeployStatus.DRY_RUN
    assert r.applied_patch_ids == ()
