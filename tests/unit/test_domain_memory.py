"""Unit: Sprint-4-Gedaechtnis-Contracts — MemoryQuery + deterministisches Lern-Signal."""

from __future__ import annotations

from datetime import datetime

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain.effect import EffectDirection, EffectHypothesis
from geo_audit_loop.domain.fix import ChangeType, FixProposal, prioritize_proposals
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.domain.memory import MemoryQuery, apply_memory_prior

FIXED = datetime(2026, 1, 1, 12, 0, 0)
_URL = "https://www.it-sicherheit.de/firewall-grundlagen"


def _proposal(
    *,
    patch_id: str,
    change_type: ChangeType,
    lever: Lever,
    confidence: float,
    pyramid_level: PyramidLevel = PyramidLevel.EXTRACTABILITY,
) -> FixProposal:
    return FixProposal(
        patch_id=patch_id,
        finding_id="f1",
        target_url=_URL,
        lever=lever,
        pyramid_level=pyramid_level,
        change_type=change_type,
        proposed_content="x",
        rationale="y",
        confidence=confidence,
    )


def _hypothesis(
    *,
    lever: Lever,
    change_type: ChangeType,
    delta: float,
    confidence: float,
    domain: str = "it-sicherheit.de",
) -> EffectHypothesis:
    direction = EffectDirection.IMPROVED if delta > 0 else EffectDirection.REGRESSED
    # Vorher/Nachher konsistent zum Delta: after - before == delta fuer delta in [-1, 1].
    before_rate = round(max(0.0, -delta), 6)
    after_rate = round(max(0.0, delta), 6)
    return EffectHypothesis(
        hypothesis_id=f"eh-r0-px-{lever.value}",
        run_id="r0",
        target_domain=domain,
        target_url=_URL,
        patch_id=f"px-{lever.value}",
        finding_id="f1",
        lever=lever,
        pyramid_level=PyramidLevel.EXTRACTABILITY,
        change_type=change_type,
        before_citation_rate=before_rate,
        after_citation_rate=after_rate,
        before_n=240,
        after_n=240,
        delta=round(delta, 6),
        direction=direction,
        confidence=confidence,
        suspected_cause="x",
        observed_at=FIXED,
    )


def test_memory_query_defaults() -> None:
    q = MemoryQuery(target_domain="it-sicherheit.de")
    assert q.top_k == c.MEMORY_TOP_K
    assert q.lever is None


def test_apply_memory_prior_empty_is_identity() -> None:
    proposals = (
        _proposal(
            patch_id="px-a",
            change_type=ChangeType.INSERT_BLOCK,
            lever=Lever.ANSWER_BLOCKS,
            confidence=0.5,
        ),
    )
    assert apply_memory_prior(proposals, ()) == proposals


def test_apply_memory_prior_boosts_matching_change_type() -> None:
    proposals = (
        _proposal(
            patch_id="px-a",
            change_type=ChangeType.INSERT_BLOCK,
            lever=Lever.ANSWER_BLOCKS,
            confidence=0.5,
        ),
    )
    hyp = _hypothesis(
        lever=Lever.ANSWER_BLOCKS,
        change_type=ChangeType.INSERT_BLOCK,
        delta=0.8,
        confidence=1.0,
    )
    adjusted = apply_memory_prior(proposals, (hyp,), weight=0.15)
    assert adjusted[0].confidence == 0.65  # 0.5 + 0.15 * 1.0


def test_apply_memory_prior_dampens_on_regression() -> None:
    proposals = (
        _proposal(
            patch_id="px-a",
            change_type=ChangeType.ADD_SCHEMA,
            lever=Lever.MACHINE_READABLE,
            confidence=0.5,
        ),
    )
    hyp = _hypothesis(
        lever=Lever.MACHINE_READABLE,
        change_type=ChangeType.ADD_SCHEMA,
        delta=-0.4,
        confidence=1.0,
    )
    adjusted = apply_memory_prior(proposals, (hyp,), weight=0.15)
    assert adjusted[0].confidence == 0.35  # 0.5 - 0.15


def test_apply_memory_prior_no_match_is_untouched() -> None:
    proposals = (
        _proposal(
            patch_id="px-a",
            change_type=ChangeType.INSERT_BLOCK,
            lever=Lever.ANSWER_BLOCKS,
            confidence=0.5,
        ),
    )
    hyp = _hypothesis(
        lever=Lever.FRESHNESS,  # anderer Hebel
        change_type=ChangeType.META_UPDATE,
        delta=0.9,
        confidence=1.0,
    )
    assert apply_memory_prior(proposals, (hyp,)) == proposals


def test_apply_memory_prior_clamps_to_unit_interval() -> None:
    proposals = (
        _proposal(
            patch_id="px-a",
            change_type=ChangeType.INSERT_BLOCK,
            lever=Lever.ANSWER_BLOCKS,
            confidence=0.95,
        ),
    )
    hyp = _hypothesis(
        lever=Lever.ANSWER_BLOCKS,
        change_type=ChangeType.INSERT_BLOCK,
        delta=1.0,
        confidence=1.0,
    )
    adjusted = apply_memory_prior(proposals, (hyp,), weight=0.5)
    assert adjusted[0].confidence == 1.0  # geklemmt


def test_memory_prior_reorders_plan() -> None:
    # Zwei Patches gleicher Pyramide; ohne Memory rankt der mit hoeherer Confidence zuerst.
    a = _proposal(
        patch_id="px-a",
        change_type=ChangeType.INSERT_BLOCK,
        lever=Lever.ANSWER_BLOCKS,
        confidence=0.60,
    )
    b = _proposal(
        patch_id="px-b",
        change_type=ChangeType.ADD_SCHEMA,
        lever=Lever.MACHINE_READABLE,
        confidence=0.66,
    )
    base_order = [p.patch_id for p in prioritize_proposals((a, b))]
    assert base_order == ["px-b", "px-a"]
    # Memory beweist, dass INSERT_BLOCK/ANSWER_BLOCKS stark wirkt -> px-a steigt und ueberholt.
    hyp = _hypothesis(
        lever=Lever.ANSWER_BLOCKS,
        change_type=ChangeType.INSERT_BLOCK,
        delta=0.9,
        confidence=1.0,
    )
    learned = apply_memory_prior((a, b), (hyp,), weight=0.15)
    learned_order = [p.patch_id for p in prioritize_proposals(learned)]
    assert learned_order == ["px-a", "px-b"]
