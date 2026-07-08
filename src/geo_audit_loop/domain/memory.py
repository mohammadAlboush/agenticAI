"""Gedaechtnis-Contracts (Sprint 4): Abfragekontext + das explizite Lern-Signal.

Der ``MemoryPort`` (siehe ``ports/memory.py``) speichert ``EffectHypothesis``-Objekte und
liefert sie fuer einen Kontext (``MemoryQuery``) zurueck. Wie eine abgerufene Hypothese den
**naechsten** Fix-Run konkret beeinflusst, ist hier als **reine, deterministische**
Domaenenfunktion ``apply_memory_prior`` festgeschrieben — kein implizites
"das LLM wird es schon nutzen" (Projektregeln §8). Sie verschiebt die Patch-Confidence
anhand erwiesener Effekte; ``prioritize_proposals`` ordnet den Plan dadurch messbar um.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from math import tanh

from pydantic import Field

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.effect import EffectDirection, EffectHypothesis
from geo_audit_loop.domain.fix import ChangeType, FixProposal
from geo_audit_loop.domain.geo import Lever, PyramidLevel


class MemoryQuery(FrozenModel):
    """Abfragekontext fuer ``MemoryPort.retrieve`` (Projektregeln §8).

    ``target_domain`` ist Pflicht und die **Isolationsgrenze**: Lernen aus einer Domain
    darf nicht ungewollt in eine andere lecken. Die uebrigen Felder sind optionale Filter
    bzw. (fuer den Chroma-Adapter) semantischer Suchkontext.
    """

    target_domain: str = Field(min_length=1)
    lever: Lever | None = None
    pyramid_level: PyramidLevel | None = None
    change_type: ChangeType | None = None
    target_url: str | None = None
    top_k: int = Field(default=c.MEMORY_TOP_K, ge=1)


def _aggregate_evidence(
    hypotheses: Sequence[EffectHypothesis], *, decay: float
) -> dict[tuple[Lever, ChangeType], float]:
    """Fasst nur **belastbare** Hypothesen je ``(Hebel, Aenderungsart)`` zu einem Evidenzwert.

    Gelernt wird ausschliesslich aus Effekten, die auch der Richtungs-Klassifikator als echt
    einstuft: ``significant`` **und** ``direction != UNCHANGED`` (d.h. das KI schliesst die Null
    aus UND das Delta ueberschreitet ``EFFECT_DIRECTION_EPSILON``). So sehen Lern-Pfad und
    Richtungs-Anzeige denselben Satz lernbarer Effekte — kein Lernen aus etwas, das die CLI als
    "GLEICH" ausweist (Projektregeln §1/§8). Das Vorzeichen kommt aus der ``direction``, nicht aus
    dem rohen Delta (konsistent mit der Klassifikation). Je Gruppe wird nach Aktualitaet sortiert
    (neueste zuerst) und geometrisch abgeklungen gewichtet: ``sign * confidence * decay**rang`` —
    aktuelle Effekte dominieren, alte/konfliktaere verwaessern. Deterministisch (feste Sortierung
    mit ``hypothesis_id``-Tiebreak); leere/nicht-belastbare Eingabe -> leeres Ergebnis.
    """
    groups: dict[tuple[Lever, ChangeType], list[EffectHypothesis]] = defaultdict(list)
    for hyp in hypotheses:
        if hyp.significant and hyp.direction is not EffectDirection.UNCHANGED:
            groups[(hyp.lever, hyp.change_type)].append(hyp)
    evidence: dict[tuple[Lever, ChangeType], float] = {}
    for key, hyps in groups.items():
        hyps.sort(key=lambda h: (h.observed_at, h.hypothesis_id), reverse=True)
        total = 0.0
        for rank, hyp in enumerate(hyps):
            sign = 1.0 if hyp.direction is EffectDirection.IMPROVED else -1.0
            total += sign * hyp.confidence * (decay**rank)
        if total != 0.0:
            evidence[key] = total
    return evidence


def apply_memory_prior(
    proposals: Sequence[FixProposal],
    hypotheses: Sequence[EffectHypothesis],
    *,
    weight: float = c.MEMORY_PRIOR_WEIGHT,
    decay: float = c.MEMORY_RECENCY_DECAY,
) -> tuple[FixProposal, ...]:
    """Nudged die Patch-Confidence anhand **erwiesener** Hypothesen (explizites Lern-Signal, §8).

    Zweistufig und statistisch fundiert (Sprint 5):

    1. ``_aggregate_evidence`` bildet je ``(Hebel, Aenderungsart)`` einen vorzeichenbehafteten
       Evidenzwert — **nur aus belastbaren** Hypothesen (``significant`` und ``direction !=
       UNCHANGED``, deckungsgleich mit dem Richtungs-Klassifikator), gewichtet mit ihrer
       statistischen Confidence und geometrischem Recency-Decay (aktuelle Effekte zaehlen mehr).
    2. Je passendem Patch wird die Confidence um ``weight * tanh(evidence)`` verschoben und auf
       ``[0, 1]`` geklemmt. ``tanh`` beschraenkt den Hub auf ``(-weight, +weight)`` und liefert
       **abnehmenden Grenznutzen**: viele schwache Belege saettigen, statt unbegrenzt zu addieren.

    Deterministisch (feste Aggregationsreihenfolge, ``round(..., 6)`` deckt libm-ULP ab). **Ohne
    belastbare Hypothesen bleibt jeder Patch bit-genau unveraendert** — der Sprint-3-Pfad
    (und jeder Lauf, dessen gemessene Effekte nur Rauschen waren) ist damit rueckwaertskompatibel.

    Args:
        proposals: Die vom Fix-Agent erzeugten Patches (vor der Priorisierung).
        hypotheses: Aus dem Gedaechtnis abgerufene, domaingleiche Effekt-Hypothesen.
        weight: Maximaler Confidence-Hub je Gruppe (Konstante ``MEMORY_PRIOR_WEIGHT``).
        decay: Geometrischer Recency-Decay je Rang (Konstante ``MEMORY_RECENCY_DECAY``).

    Returns:
        Die Patches mit ggf. angepasster Confidence (unveraenderte Instanzen bei kein Treffer).
    """
    evidence = _aggregate_evidence(hypotheses, decay=decay)
    if not evidence:
        return tuple(proposals)
    adjusted: list[FixProposal] = []
    for proposal in proposals:
        signal = evidence.get((proposal.lever, proposal.change_type), 0.0)
        if signal == 0.0:
            adjusted.append(proposal)
            continue
        nudge = round(weight * tanh(signal), 6)
        new_confidence = max(0.0, min(1.0, round(proposal.confidence + nudge, 6)))
        adjusted.append(proposal.model_copy(update={"confidence": new_confidence}))
    return tuple(adjusted)
