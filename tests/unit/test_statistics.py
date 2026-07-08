"""Unit: reine Zwei-Proportionen-Statistik (Wilson-Intervall + Newcombe-Difference-KI).

Gegen publizierte Referenzwerte verifiziert (Newcombe 1998, Methode 10: 56/70 vs. 48/80
-> KI der Differenz [0.0524, 0.3339]). Deterministisch, kein I/O, kein RNG.
"""

from __future__ import annotations

import pytest

from geo_audit_loop.domain.statistics import (
    conservative_effect,
    is_significant,
    proportion_diff_ci,
    wilson_interval,
)


def test_wilson_reference_values() -> None:
    # x=0 / x=n: das Wald-Intervall waere entartet [0,0]/[1,1]; Wilson ist es nicht.
    assert wilson_interval(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-4)
    assert wilson_interval(10, 10) == pytest.approx((0.7225, 1.0), abs=1e-4)
    assert wilson_interval(48, 80) == pytest.approx((0.4905, 0.7004), abs=1e-4)
    assert wilson_interval(56, 70) == pytest.approx((0.6918, 0.8770), abs=1e-4)


def test_wilson_symmetry() -> None:
    lo_a, hi_a = wilson_interval(3, 10)
    lo_b, hi_b = wilson_interval(7, 10)  # Komplement -> gespiegeltes Intervall
    assert lo_a == pytest.approx(1.0 - hi_b, abs=1e-9)
    assert hi_a == pytest.approx(1.0 - lo_b, abs=1e-9)


def test_wilson_empty_sample_is_maximally_uncertain() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_newcombe_difference_ci_matches_publication() -> None:
    # Newcombe (1998), Methode 10: after=56/70 (0.80), before=48/80 (0.60) -> delta=+0.20,
    # 95%-KI der Differenz = [0.0524, 0.3339]. Der klassische Validierungsfall.
    ci_low, ci_high = proportion_diff_ci(48, 80, 56, 70)
    assert (ci_low, ci_high) == pytest.approx((0.0524, 0.3339), abs=1e-4)


def test_diff_ci_empty_phase_is_maximally_uncertain() -> None:
    assert proportion_diff_ci(0, 0, 5, 10) == (-1.0, 1.0)
    assert proportion_diff_ci(5, 10, 0, 0) == (-1.0, 1.0)


def test_significance_gate_rejects_noise_and_accepts_strong_effect() -> None:
    # Rauschen: +0.05 bei n=240 -> KI umschliesst die Null -> nicht signifikant.
    noise_low, noise_high = proportion_diff_ci(120, 240, 132, 240)
    assert not is_significant(noise_low, noise_high)
    assert conservative_effect(noise_low, noise_high) == 0.0

    # Klarer Lift: 12/240 -> 228/240 -> KI klar ueber der Null -> signifikant, hohe Confidence.
    strong_low, strong_high = proportion_diff_ci(12, 240, 228, 240)
    assert is_significant(strong_low, strong_high)
    assert conservative_effect(strong_low, strong_high) > 0.8


def test_conservative_effect_is_near_zero_edge() -> None:
    assert conservative_effect(0.2, 0.5) == 0.2  # ganz positiv -> untere Grenze
    assert conservative_effect(-0.5, -0.2) == 0.2  # ganz negativ -> Betrag der oberen Grenze
    assert conservative_effect(-0.1, 0.3) == 0.0  # umschliesst Null -> kein garantierter Effekt


def test_conservative_effect_grows_with_sample_size() -> None:
    # Gleiches Delta (0 -> 1), groessere Stichprobe -> engeres KI -> hoehere Confidence.
    small = conservative_effect(*proportion_diff_ci(0, 10, 10, 10))
    large = conservative_effect(*proportion_diff_ci(0, 200, 200, 200))
    assert 0.0 < small < large <= 1.0


def test_statistics_are_deterministic() -> None:
    assert proportion_diff_ci(12, 240, 228, 240) == proportion_diff_ci(12, 240, 228, 240)
    assert wilson_interval(37, 240) == wilson_interval(37, 240)
