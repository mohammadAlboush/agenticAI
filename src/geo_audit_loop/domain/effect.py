"""Effekt-Contracts (Sprint 4): die Vorher/Nachher-Messung eines Fix-Laufs.

Nachdem die freigegebenen Patches (Dry-Run) angewandt wurden, misst der Loop denselben
Probe-Matrix-Schnitt erneut (``ProbePhase.REPROBE``) und vergleicht die Zitationsrate je
Zielseite mit der Baseline. Das Ergebnis je Patch ist eine **strukturierte**
``EffectHypothesis`` (Projektregeln §3.2/§8): Vorher-Metrik, Nachher-Metrik, vermutete
Ursache (der ``(Lever, ChangeType)``-Bezug — kein Freitext) und eine **deterministisch**
berechnete Confidence. Die Formung ist eine reine Domaenenfunktion ohne I/O (kein LLM,
kein RNG) — so bleibt der Offline-Pfad bit-reproduzierbar (Projektregeln §7).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from statistics import fmean
from typing import Self

from pydantic import Field, model_validator

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.fix import ChangeType, FixProposal
from geo_audit_loop.domain.geo import LEVER_LABELS, PYRAMID_LABELS, Lever, PyramidLevel
from geo_audit_loop.domain.metrics import url_citation_counts
from geo_audit_loop.domain.probe import ProbeResult, ProbeStatus
from geo_audit_loop.domain.statistics import (
    conservative_effect,
    is_significant,
    proportion_diff_ci,
)


class EffectDirection(StrEnum):
    """Richtung des gemessenen Effekts (geschlossenes Vokabular, keine Magic Strings)."""

    IMPROVED = "improved"  # Zitationsrate signifikant gestiegen
    REGRESSED = "regressed"  # Zitationsrate signifikant gefallen
    UNCHANGED = "unchanged"  # innerhalb der Toleranz -> kein belastbarer Effekt


class EffectHypothesis(FrozenModel):
    """Vorher/Nachher-Effekt eines Patches als strukturierte Lern-Hypothese (Projektregeln §8).

    Traegt die Provenienz (``patch_id`` -> ``FixProposal`` -> ``finding_id``), die
    vermutete Ursache als ``(lever, change_type)``-Bezug, die Vorher/Nachher-Zitationsrate
    samt Stichprobengroessen, ein **statistisches 95%-Konfidenzintervall** des Deltas
    (``ci_low``/``ci_high``, Newcombe/Wilson — Sprint 5) und eine daraus **deterministisch**
    abgeleitete ``confidence`` (die statistisch abgesicherte Effektstaerke). Das abgeleitete
    ``significant`` sagt, ob das KI die Null ausschliesst — nur dann ist der Effekt belastbar
    und darf den naechsten Fix-Run beeinflussen. Die ``hypothesis_id`` ist deterministisch
    (kein Zufall) — reproduzierbar und upsert-faehig.
    """

    hypothesis_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    target_url: str = Field(min_length=1)
    patch_id: str = Field(min_length=1)  # Provenienz zum FixProposal
    finding_id: str = Field(min_length=1)  # Provenienz zum AuditFinding
    lever: Lever
    pyramid_level: PyramidLevel
    change_type: ChangeType
    template_id: str | None = None
    before_citation_rate: float = Field(ge=0.0, le=1.0)
    after_citation_rate: float = Field(ge=0.0, le=1.0)
    before_n: int = Field(ge=0)  # Anzahl OK-Probes der Baseline
    after_n: int = Field(ge=0)  # Anzahl OK-Probes der Re-Probe
    delta: float = Field(ge=-1.0, le=1.0)  # after - before
    # 95%-Konfidenzintervall des Deltas (Newcombe Methode 10). ``None`` nur fuer
    # hand-konstruierte Hypothesen ohne Messung; der Produzent setzt es stets.
    ci_low: float | None = Field(default=None, ge=-1.0, le=1.0)
    ci_high: float | None = Field(default=None, ge=-1.0, le=1.0)
    # Ob das Delta-KI die Null ausschliesst -> statistisch belastbarer Effekt (§8). Regulaeres
    # Feld (kein computed_field: das kollidierte mit ``extra='forbid'`` beim JSON-Roundtrip);
    # der Produzent setzt es aus dem KI, ein Validator erzwingt Konsistenz mit dem KI.
    significant: bool = False
    direction: EffectDirection
    confidence: float = Field(ge=0.0, le=1.0)  # = conservative_effect(ci) beim Produzenten
    suspected_cause: str = Field(min_length=1)  # strukturiert aus (lever, change_type) abgeleitet
    observed_at: datetime

    @model_validator(mode="after")
    def _delta_consistent(self) -> Self:
        """Das persistierte ``delta`` muss exakt ``after - before`` sein (Kontrakt-Integritaet)."""
        expected = round(self.after_citation_rate - self.before_citation_rate, 6)
        if abs(self.delta - expected) > 1e-9:
            raise ValueError("delta != after_citation_rate - before_citation_rate")
        return self

    @model_validator(mode="after")
    def _ci_consistent(self) -> Self:
        """Falls ein KI vorliegt: geordnet, das Delta enthaltend, und ``significant`` konsistent."""
        if self.ci_low is None or self.ci_high is None:
            return self
        if self.ci_low > self.ci_high + 1e-9:
            raise ValueError("ci_low > ci_high")
        if not (self.ci_low - 1e-6 <= self.delta <= self.ci_high + 1e-6):
            raise ValueError("delta ausserhalb des Konfidenzintervalls")
        if self.significant != is_significant(self.ci_low, self.ci_high):
            raise ValueError("significant inkonsistent mit dem Konfidenzintervall")
        return self


class EffectReport(FrozenModel):
    """Ergebnis des Effekt-Re-Probings: die Hypothesen ueber alle angewandten Patches.

    Parallel zu ``FixPlan``/``AuditReport`` ein Run-Artefakt; fliesst deterministisch in
    den Report-Fingerprint (Projektregeln §7) und wird ueber den ``MemoryPort`` gespeichert.
    """

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    generated_at: datetime
    prompt_version: str = Field(min_length=1)  # welche fix_agent.vN den getesteten Plan erzeugte
    reprobe_matrix_size: int = Field(ge=0)  # Anzahl OK-Re-Probes (Nachher-Nenner)
    mean_delta: float = Field(ge=-1.0, le=1.0)
    n_improved: int = Field(ge=0)
    hypotheses: tuple[EffectHypothesis, ...] = ()


def derive_hypothesis_id(run_id: str, patch_id: str) -> str:
    """Deterministische Hypothesen-ID aus Run + Patch (kein Zufall => reproduzierbar/upsert)."""
    return f"eh-{run_id}-{patch_id}"


def classify_direction(delta: float, *, significant: bool) -> EffectDirection:
    """Ordnet ein Delta einer Richtung zu — nur bei statistischer Signifikanz.

    Ein Effekt gilt erst dann als IMPROVED/REGRESSED, wenn er (a) **signifikant** ist (das
    Delta-KI schliesst die Null aus) UND (b) die Effektstaerke-Untergrenze
    ``EFFECT_DIRECTION_EPSILON`` ueberschreitet. Nicht-signifikante oder winzige Deltas sind
    UNCHANGED -> der Lern-Loop verankert keine Hypothese in Rauschen (Projektregeln §1/§8).
    """
    if not significant:
        return EffectDirection.UNCHANGED
    if delta > c.EFFECT_DIRECTION_EPSILON:
        return EffectDirection.IMPROVED
    if delta < -c.EFFECT_DIRECTION_EPSILON:
        return EffectDirection.REGRESSED
    return EffectDirection.UNCHANGED


def _suspected_cause(proposal: FixProposal, direction: EffectDirection) -> str:
    """Baut die strukturierte Ursache aus Hebel + Aenderungsart (kein Freitext-LLM)."""
    lever_label = LEVER_LABELS[proposal.lever]
    level_label = PYRAMID_LABELS[proposal.pyramid_level]
    verb = {
        EffectDirection.IMPROVED: "erhoehte",
        EffectDirection.REGRESSED: "senkte",
        EffectDirection.UNCHANGED: "veraenderte nicht messbar",
    }[direction]
    return (
        f"Aenderung '{proposal.change_type.value}' am Hebel '{lever_label}' "
        f"({level_label}) {verb} die Zitationsrate der Zielseite."
    )


def form_effect_report(
    *,
    run_id: str,
    target_domain: str,
    before_probes: Sequence[ProbeResult],
    after_probes: Sequence[ProbeResult],
    applied: Sequence[FixProposal],
    prompt_version: str,
    generated_at: datetime,
) -> EffectReport:
    """Bildet aus Baseline- und Re-Probe-Ergebnissen je angewandtem Patch eine Hypothese.

    Reine Domaenenfunktion (kein I/O, kein LLM, kein RNG). Attribution erfolgt **pro
    Zielseite**: der Effekt eines Patches ist die Differenz seiner URL-Zitationsrate
    zwischen Re-Probe und Baseline. Ergebnis ist deterministisch nach ``patch_id`` sortiert.

    Args:
        run_id: Der Lauf, zu dem der Effekt gehoert.
        target_domain: Die Zieldomain (Isolationsgrenze des Gedaechtnisses).
        before_probes: OK/Fehler-Probes der Baseline-Phase.
        after_probes: Probes der Re-Probe-Phase (nach dem Dry-Run-Deploy).
        applied: Die tatsaechlich (freigegebenen) angewandten Patches.
        prompt_version: Version des Fix-Prompts, der den getesteten Plan erzeugte.
        generated_at: Zeitstempel (injizierte Uhr) fuer die Artefakte.

    Returns:
        Ein ``EffectReport`` mit einer ``EffectHypothesis`` je angewandtem Patch.
    """
    hypotheses: list[EffectHypothesis] = []
    for proposal in sorted(applied, key=lambda p: p.patch_id):
        before_hits, before_n = url_citation_counts(before_probes, proposal.target_url)
        after_hits, after_n = url_citation_counts(after_probes, proposal.target_url)
        # Delta aus den GERUNDETEN Raten ableiten (exakt die, die persistiert werden), damit der
        # _delta_consistent-Validator zustimmt. Sonst driften bei gebrochenen Raten (z.B. 1/3, 2/3)
        # unabhaengig gerundete Felder um ~1e-6 vom aus Rohwerten berechneten Delta ab -> Crash.
        before_cr = round(before_hits / before_n, 6) if before_n else 0.0
        after_cr = round(after_hits / after_n, 6) if after_n else 0.0
        delta = round(after_cr - before_cr, 6)
        # Statistik (Sprint 5): 95%-KI des Deltas aus den Roh-Counts (Newcombe/Wilson).
        # Signifikanz + Confidence folgen ausschliesslich aus dem KI, nicht aus einer Heuristik.
        ci_low, ci_high = proportion_diff_ci(before_hits, before_n, after_hits, after_n)
        significant = is_significant(ci_low, ci_high)
        direction = classify_direction(delta, significant=significant)
        hypotheses.append(
            EffectHypothesis(
                hypothesis_id=derive_hypothesis_id(run_id, proposal.patch_id),
                run_id=run_id,
                target_domain=target_domain,
                target_url=proposal.target_url,
                patch_id=proposal.patch_id,
                finding_id=proposal.finding_id,
                lever=proposal.lever,
                pyramid_level=proposal.pyramid_level,
                change_type=proposal.change_type,
                template_id=proposal.template_id,
                before_citation_rate=before_cr,
                after_citation_rate=after_cr,
                before_n=before_n,
                after_n=after_n,
                delta=delta,
                ci_low=ci_low,
                ci_high=ci_high,
                significant=significant,
                direction=direction,
                confidence=conservative_effect(ci_low, ci_high),
                suspected_cause=_suspected_cause(proposal, direction),
                observed_at=generated_at,
            )
        )
    mean_delta = round(fmean(h.delta for h in hypotheses), 6) if hypotheses else 0.0
    n_improved = sum(1 for h in hypotheses if h.direction is EffectDirection.IMPROVED)
    reprobe_size = sum(1 for r in after_probes if r.status is ProbeStatus.OK)
    return EffectReport(
        run_id=run_id,
        target_domain=target_domain,
        generated_at=generated_at,
        prompt_version=prompt_version,
        reprobe_matrix_size=reprobe_size,
        mean_delta=mean_delta,
        n_improved=n_improved,
        hypotheses=tuple(hypotheses),
    )
