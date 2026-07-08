"""Unit: Sprint-4-Effekt-Contracts + deterministische Formung (kein I/O, kein RNG)."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from geo_audit_loop.domain.effect import (
    EffectDirection,
    EffectHypothesis,
    classify_direction,
    compute_confidence,
    derive_hypothesis_id,
    form_effect_report,
)
from geo_audit_loop.domain.fix import ChangeType, FixProposal
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.domain.metrics import url_citation_rate
from geo_audit_loop.domain.probe import (
    Citation,
    EngineId,
    ProbeResult,
    ProbeStatus,
    ProbeUsage,
)

FIXED = datetime(2026, 1, 1, 12, 0, 0)
_URL = "https://www.it-sicherheit.de/firewall-grundlagen"


def _probe(*, cites_url: str | None, status: ProbeStatus = ProbeStatus.OK) -> ProbeResult:
    citations = (
        (Citation(url=cites_url, engine=EngineId.GEMINI, rank=1),) if cites_url is not None else ()
    )
    return ProbeResult(
        run_id="r1",
        engine_id=EngineId.GEMINI,
        model="mock",
        prompt_id="p1",
        prompt_version="v1",
        citations=citations,
        status=status,
        probed_at=FIXED,
    )


def _proposal(
    *,
    patch_id: str = "px-f1-insert_block",
    change_type: ChangeType = ChangeType.INSERT_BLOCK,
    lever: Lever = Lever.FACT_DENSITY,
    pyramid_level: PyramidLevel = PyramidLevel.SUBSTANCE,
) -> FixProposal:
    return FixProposal(
        patch_id=patch_id,
        finding_id="f1",
        target_url=_URL,
        lever=lever,
        pyramid_level=pyramid_level,
        change_type=change_type,
        proposed_content="Ein Firewall filtert Netzwerkverkehr anhand von Regeln.",
        rationale="Template t2 verlangt Faktendichte.",
        confidence=0.78,
    )


def test_url_citation_rate_counts_ok_probes_only() -> None:
    probes = [
        _probe(cites_url=_URL),
        _probe(cites_url=_URL),
        _probe(cites_url=None),
        _probe(cites_url=_URL, status=ProbeStatus.ERROR),  # zaehlt nicht in den Nenner
    ]
    rate, n = url_citation_rate(probes, _URL)
    assert n == 3
    assert rate == pytest.approx(2 / 3)


def test_url_citation_rate_empty_is_zero() -> None:
    assert url_citation_rate([], _URL) == (0.0, 0)


def test_compute_confidence_is_monotone_and_bounded() -> None:
    assert compute_confidence(0.0, 100) == 0.0
    # groesseres Delta -> hoehere Confidence (gleiche Stichprobe)
    assert compute_confidence(0.5, 100) < compute_confidence(0.9, 100)
    # groessere Stichprobe -> hoehere Confidence (gleiches Delta)
    assert compute_confidence(0.5, 5) < compute_confidence(0.5, 500)
    assert 0.0 <= compute_confidence(1.0, 1_000_000) <= 1.0


def test_compute_confidence_is_deterministic() -> None:
    assert compute_confidence(0.33, 240) == compute_confidence(0.33, 240)


def test_classify_direction_tolerance_band() -> None:
    assert classify_direction(0.5) is EffectDirection.IMPROVED
    assert classify_direction(-0.5) is EffectDirection.REGRESSED
    assert classify_direction(0.0) is EffectDirection.UNCHANGED
    assert classify_direction(0.001) is EffectDirection.UNCHANGED  # unter EPSILON


def test_hypothesis_rejects_inconsistent_delta() -> None:
    with pytest.raises(ValidationError):
        EffectHypothesis(
            hypothesis_id=derive_hypothesis_id("r1", "px-f1-insert_block"),
            run_id="r1",
            target_domain="it-sicherheit.de",
            target_url=_URL,
            patch_id="px-f1-insert_block",
            finding_id="f1",
            lever=Lever.FACT_DENSITY,
            pyramid_level=PyramidLevel.SUBSTANCE,
            change_type=ChangeType.INSERT_BLOCK,
            before_citation_rate=0.1,
            after_citation_rate=0.9,
            before_n=100,
            after_n=100,
            delta=0.5,  # inkonsistent: 0.9 - 0.1 = 0.8
            direction=EffectDirection.IMPROVED,
            confidence=0.5,
            suspected_cause="x",
            observed_at=FIXED,
        )


def test_form_effect_report_measures_positive_delta() -> None:
    n = 250  # grosse Stichprobe -> hohe Confidence (n/(n+SHRINKAGE))
    before = [_probe(cites_url=None) for _ in range(n)]  # Baseline: nie zitiert
    after = [_probe(cites_url=_URL) for _ in range(n)]  # Re-Probe: immer zitiert (Boost)
    report = form_effect_report(
        run_id="r1",
        target_domain="it-sicherheit.de",
        before_probes=before,
        after_probes=after,
        applied=[_proposal()],
        prompt_version="v2",
        generated_at=FIXED,
    )
    assert len(report.hypotheses) == 1
    hyp = report.hypotheses[0]
    assert hyp.before_citation_rate == 0.0
    assert hyp.after_citation_rate == 1.0
    assert hyp.delta == 1.0
    assert hyp.direction is EffectDirection.IMPROVED
    assert hyp.confidence == compute_confidence(1.0, n)
    assert hyp.confidence > 0.95
    assert hyp.hypothesis_id == "eh-r1-px-f1-insert_block"
    assert report.n_improved == 1
    assert report.mean_delta == 1.0
    assert report.reprobe_matrix_size == n


def test_form_effect_report_is_deterministic_and_sorted() -> None:
    before = [_probe(cites_url=None) for _ in range(4)]
    after = [_probe(cites_url=_URL) for _ in range(4)]
    applied = [
        _proposal(patch_id="px-b", change_type=ChangeType.ADD_SCHEMA),
        _proposal(patch_id="px-a", change_type=ChangeType.INSERT_BLOCK),
    ]
    r1 = form_effect_report(
        run_id="r1",
        target_domain="it-sicherheit.de",
        before_probes=before,
        after_probes=after,
        applied=applied,
        prompt_version="v2",
        generated_at=FIXED,
    )
    r2 = form_effect_report(
        run_id="r1",
        target_domain="it-sicherheit.de",
        before_probes=before,
        after_probes=after,
        applied=list(reversed(applied)),
        prompt_version="v2",
        generated_at=FIXED,
    )
    assert r1 == r2  # Reihenfolge der Eingabe egal -> nach patch_id sortiert
    assert [h.patch_id for h in r1.hypotheses] == ["px-a", "px-b"]


def test_form_effect_report_survives_fractional_rates() -> None:
    # Regression: gebrochene Raten (1/3 -> 2/3) duerfen den _delta_consistent-Validator NICHT
    # verletzen (Delta wird aus den gerundeten Raten abgeleitet). Frueher: ValidationError-Crash.
    before = [_probe(cites_url=_URL), _probe(cites_url=None), _probe(cites_url=None)]  # 1/3
    after = [_probe(cites_url=_URL), _probe(cites_url=_URL), _probe(cites_url=None)]  # 2/3
    report = form_effect_report(
        run_id="r1",
        target_domain="it-sicherheit.de",
        before_probes=before,
        after_probes=after,
        applied=[_proposal()],
        prompt_version="v2",
        generated_at=FIXED,
    )
    hyp = report.hypotheses[0]
    assert hyp.before_citation_rate == round(1 / 3, 6)
    assert hyp.after_citation_rate == round(2 / 3, 6)
    # Delta ist konsistent mit den gespeicherten (gerundeten) Raten:
    assert hyp.delta == round(hyp.after_citation_rate - hyp.before_citation_rate, 6)
    assert hyp.direction is EffectDirection.IMPROVED


def test_form_effect_report_empty_applied() -> None:
    report = form_effect_report(
        run_id="r1",
        target_domain="it-sicherheit.de",
        before_probes=[_probe(cites_url=None)],
        after_probes=[_probe(cites_url=None)],
        applied=[],
        prompt_version="v2",
        generated_at=FIXED,
    )
    assert report.hypotheses == ()
    assert report.mean_delta == 0.0
    assert report.n_improved == 0


def test_hypothesis_roundtrip() -> None:
    _ = ProbeUsage()  # Contract-Import-Smoke
    report = form_effect_report(
        run_id="r1",
        target_domain="it-sicherheit.de",
        before_probes=[_probe(cites_url=None)],
        after_probes=[_probe(cites_url=_URL)],
        applied=[_proposal()],
        prompt_version="v2",
        generated_at=FIXED,
    )
    hyp = report.hypotheses[0]
    assert EffectHypothesis.model_validate_json(hyp.model_dump_json()) == hyp
