"""Unit: Sprint-4-Gedaechtnis-Contracts — MemoryQuery + deterministisches Lern-Signal."""

from __future__ import annotations

from datetime import datetime
from math import tanh

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
    significant: bool = True,
    observed_at: datetime = FIXED,
    hid: str | None = None,
) -> EffectHypothesis:
    direction = EffectDirection.IMPROVED if delta > 0 else EffectDirection.REGRESSED
    # Vorher/Nachher konsistent zum Delta: after - before == delta fuer delta in [-1, 1].
    before_rate = round(max(0.0, -delta), 6)
    after_rate = round(max(0.0, delta), 6)
    # Ein KI konstruieren, das (a) das Delta enthaelt und (b) genau ``significant`` erfuellt.
    mag = abs(delta)
    if significant:
        edge_near = round(mag / 2, 6)  # strikt zwischen 0 und |delta|
        edge_far = round(min(1.0, mag + (1.0 - mag) / 2), 6)  # ueber |delta|, <= 1
        ci_low, ci_high = (edge_near, edge_far) if delta >= 0 else (-edge_far, -edge_near)
    else:
        ci_low, ci_high = round(-mag - 0.05, 6), round(mag + 0.05, 6)  # umschliesst die Null
    return EffectHypothesis(
        hypothesis_id=hid if hid is not None else f"eh-r0-px-{lever.value}",
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
        ci_low=ci_low,
        ci_high=ci_high,
        significant=significant,
        direction=direction,
        confidence=confidence,
        suspected_cause="x",
        observed_at=observed_at,
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


def _expected(base: float, evidence: float, weight: float = c.MEMORY_PRIOR_WEIGHT) -> float:
    """Spiegelt die (bounded) Nudge-Formel: base + weight * tanh(evidence), geklemmt auf [0,1]."""
    return max(0.0, min(1.0, round(base + weight * tanh(evidence), 6)))


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
    # Bounded: steigt, aber hoechstens um weight; abnehmender Grenznutzen (tanh).
    assert adjusted[0].confidence == _expected(0.5, 1.0, weight=0.15)
    assert 0.5 < adjusted[0].confidence < 0.5 + 0.15


def test_apply_memory_prior_ignores_non_significant_noise() -> None:
    # KERN-VERBESSERUNG (Sprint 5): ein NICHT signifikanter Effekt (KI umschliesst die Null)
    # ist Rauschen und darf den naechsten Fix-Run NICHT beeinflussen.
    proposals = (
        _proposal(
            patch_id="px-a",
            change_type=ChangeType.INSERT_BLOCK,
            lever=Lever.ANSWER_BLOCKS,
            confidence=0.5,
        ),
    )
    noisy = _hypothesis(
        lever=Lever.ANSWER_BLOCKS,
        change_type=ChangeType.INSERT_BLOCK,
        delta=0.05,
        confidence=0.4,
        significant=False,
    )
    assert apply_memory_prior(proposals, (noisy,)) == proposals


def test_apply_memory_prior_ignores_significant_but_unchanged_effect() -> None:
    # Grenzfall (bei grossem n erreichbar): ein Effekt ist statistisch signifikant (KI ohne Null),
    # aber sein Delta liegt unter EFFECT_DIRECTION_EPSILON -> direction=UNCHANGED. Lern-Pfad und
    # Richtungs-Klassifikator muessen denselben Satz sehen: die CLI zeigt "GLEICH" -> nicht lernen.
    proposals = (
        _proposal(
            patch_id="px-a",
            change_type=ChangeType.INSERT_BLOCK,
            lever=Lever.ANSWER_BLOCKS,
            confidence=0.5,
        ),
    )
    tiny = EffectHypothesis(
        hypothesis_id="eh-tiny",
        run_id="r0",
        target_domain="it-sicherheit.de",
        target_url=_URL,
        patch_id="px-tiny",
        finding_id="f1",
        lever=Lever.ANSWER_BLOCKS,
        pyramid_level=PyramidLevel.EXTRACTABILITY,
        change_type=ChangeType.INSERT_BLOCK,
        before_citation_rate=0.0,
        after_citation_rate=0.008,
        before_n=1000,
        after_n=1000,
        delta=0.008,  # unter EFFECT_DIRECTION_EPSILON (0.01)
        ci_low=0.001,  # KI schliesst die Null aus -> significant
        ci_high=0.02,
        significant=True,
        direction=EffectDirection.UNCHANGED,  # trotz Signifikanz: zu klein fuer eine Richtung
        confidence=0.001,
        suspected_cause="x",
        observed_at=FIXED,
    )
    assert apply_memory_prior(proposals, (tiny,)) == proposals


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
    assert adjusted[0].confidence == _expected(0.5, -1.0, weight=0.15)
    assert 0.5 - 0.15 < adjusted[0].confidence < 0.5


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
    assert adjusted[0].confidence == 1.0  # 0.95 + 0.5*tanh(1) > 1 -> geklemmt


def test_apply_memory_prior_recency_weights_newer_evidence_more() -> None:
    # Zwei signifikante, GEGENSAETZLICHE Effekte fuer denselben Hebel; der neuere gewinnt.
    proposals = (
        _proposal(
            patch_id="px-a",
            change_type=ChangeType.INSERT_BLOCK,
            lever=Lever.ANSWER_BLOCKS,
            confidence=0.5,
        ),
    )
    newer_positive = _hypothesis(
        lever=Lever.ANSWER_BLOCKS,
        change_type=ChangeType.INSERT_BLOCK,
        delta=0.8,
        confidence=1.0,
        observed_at=datetime(2026, 6, 1, 12, 0, 0),
        hid="eh-new",
    )
    older_negative = _hypothesis(
        lever=Lever.ANSWER_BLOCKS,
        change_type=ChangeType.INSERT_BLOCK,
        delta=-0.8,
        confidence=1.0,
        observed_at=datetime(2026, 1, 1, 12, 0, 0),
        hid="eh-old",
    )
    adjusted = apply_memory_prior(proposals, (older_negative, newer_positive))
    # Netto-Evidenz = +1.0 (neu, Rang 0) - 0.5*1.0 (alt, Rang 1) = +0.5 -> Confidence steigt.
    assert adjusted[0].confidence == _expected(0.5, 1.0 - c.MEMORY_RECENCY_DECAY)
    assert adjusted[0].confidence > 0.5


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
