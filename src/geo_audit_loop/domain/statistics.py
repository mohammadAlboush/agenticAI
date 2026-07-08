"""Reine Zwei-Proportionen-Statistik fuer die Effekt-Messung (kein I/O, kein RNG).

Der Lern-Loop misst je Zielseite eine Zitationsrate **vorher** (Baseline) und **nachher**
(Re-Probe). Ob der beobachtete Unterschied ein echter Effekt oder nur Stichproben-Rauschen
ist, entscheidet hier ein **statistisches Konfidenzintervall**, nicht mehr eine Ad-hoc-Formel
(Projektregeln §1: wissenschaftliche Aussagekraft; §7: Reproduzierbarkeit).

Verwendet werden zwei etablierte, closed-form Verfahren — ganz ohne ``scipy``:

* **Wilson-Score-Intervall** fuer eine einzelne Proportion (robust auch bei p nahe 0/1 und
  kleinem n, wo das naive Wald-Intervall versagt).
* **Newcombe (1998), Methode 10** (MOVER-W): das KI der **Differenz** zweier unabhaengiger
  Proportionen wird aus deren Wilson-Intervallen zusammengesetzt. Gegen den in Newcombes
  Arbeit publizierten Beispielwert verifiziert (56/70 vs. 48/80 -> KI [0.0524, 0.3339]).

Alle Rueckgaben sind auf ``_ROUND`` Nachkommastellen gerundet -> plattformstabile
Bit-Reproduzierbarkeit (dieselbe Rundungsstrategie wie im uebrigen Domaenen-Code).
"""

from __future__ import annotations

from math import sqrt
from typing import Final

from geo_audit_loop.config import constants as c

#: Nachkommastellen fuer plattformstabiles Runden (deckt libm-ULP-Differenzen ab).
_ROUND: Final = 6


def wilson_interval(successes: int, n: int, z: float = c.EFFECT_CI_Z) -> tuple[float, float]:
    """Wilson-Score-Konfidenzintervall fuer eine Proportion ``successes/n``.

    Args:
        successes: Anzahl der Treffer (0 <= successes <= n).
        n: Stichprobengroesse.
        z: Normalquantil (Default: zweiseitig 95 %).

    Returns:
        ``(low, high)`` in ``[0, 1]``. Bei ``n <= 0`` das maximal unsichere ``(0.0, 1.0)``.
    """
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z / denom) * sqrt(p * (1.0 - p) / n + z2 / (4 * n * n))
    low = max(0.0, center - margin)
    high = min(1.0, center + margin)
    return (round(low, _ROUND), round(high, _ROUND))


def proportion_diff_ci(
    before_hits: int,
    before_n: int,
    after_hits: int,
    after_n: int,
    z: float = c.EFFECT_CI_Z,
) -> tuple[float, float]:
    """Konfidenzintervall der Differenz ``delta = p_after - p_before`` (Newcombe Methode 10).

    Das KI der Differenz zweier **unabhaengiger** Proportionen wird aus den beiden
    Wilson-Intervallen zusammengesetzt (MOVER-W / "square-and-add"). Bei leerer Baseline
    oder leerer Re-Probe ist das Delta unbestimmbar -> maximal unsicheres ``(-1.0, 1.0)``.

    Args:
        before_hits: Treffer in der Baseline.
        before_n: OK-Probes der Baseline (Nenner vorher).
        after_hits: Treffer in der Re-Probe.
        after_n: OK-Probes der Re-Probe (Nenner nachher).
        z: Normalquantil (Default: zweiseitig 95 %).

    Returns:
        ``(ci_low, ci_high)`` fuer ``delta`` in ``[-1, 1]``, auf ``_ROUND`` gerundet.
    """
    if before_n <= 0 or after_n <= 0:
        return (-1.0, 1.0)
    p_before = before_hits / before_n
    p_after = after_hits / after_n
    lb, ub = wilson_interval(before_hits, before_n, z)
    la, ua = wilson_interval(after_hits, after_n, z)
    delta = p_after - p_before
    # MOVER-W fuer theta = p_after - p_before: die untere Grenze kombiniert die untere
    # Wilson-Grenze von "nachher" mit der oberen von "vorher" und umgekehrt.
    low = delta - sqrt((p_after - la) ** 2 + (ub - p_before) ** 2)
    high = delta + sqrt((ua - p_after) ** 2 + (p_before - lb) ** 2)
    return (round(max(-1.0, low), _ROUND), round(min(1.0, high), _ROUND))


def is_significant(ci_low: float, ci_high: float) -> bool:
    """Ob das Differenz-KI die Null ausschliesst (=> statistisch belastbarer Effekt)."""
    return ci_low > 0.0 or ci_high < 0.0


def conservative_effect(ci_low: float, ci_high: float) -> float:
    """Statistisch abgesicherte Effektstaerke: Abstand der Null zur naechsten KI-Kante.

    Liegt das ganze KI ueber der Null, ist das die untere Grenze; liegt es ganz darunter,
    der Betrag der oberen Grenze; schliesst das KI die Null ein, ist der garantierte Effekt
    ``0``. Der Wert dient als **deterministische Confidence** einer ``EffectHypothesis``:
    monoton in Effektstaerke (verschiebt das KI von der Null weg) UND in der Stichprobe
    (verengt das KI) — und exakt ``0``, wenn der Effekt nicht signifikant ist.

    Returns:
        Ein Wert in ``[0, 1]`` auf ``_ROUND`` Nachkommastellen.
    """
    if ci_low > 0.0:
        return round(ci_low, _ROUND)
    if ci_high < 0.0:
        return round(-ci_high, _ROUND)
    return 0.0
