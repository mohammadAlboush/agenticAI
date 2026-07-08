"""Gedaechtnis-Contracts (Sprint 4): Abfragekontext + das explizite Lern-Signal.

Der ``MemoryPort`` (siehe ``ports/memory.py``) speichert ``EffectHypothesis``-Objekte und
liefert sie fuer einen Kontext (``MemoryQuery``) zurueck. Wie eine abgerufene Hypothese den
**naechsten** Fix-Run konkret beeinflusst, ist hier als **reine, deterministische**
Domaenenfunktion ``apply_memory_prior`` festgeschrieben — kein implizites
"das LLM wird es schon nutzen" (Projektregeln §8). Sie verschiebt die Patch-Confidence
anhand erwiesener Effekte; ``prioritize_proposals`` ordnet den Plan dadurch messbar um.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.effect import EffectHypothesis
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


def apply_memory_prior(
    proposals: Sequence[FixProposal],
    hypotheses: Sequence[EffectHypothesis],
    *,
    weight: float = c.MEMORY_PRIOR_WEIGHT,
) -> tuple[FixProposal, ...]:
    """Nudged die Patch-Confidence anhand erwiesener Hypothesen (explizites Lern-Signal, §8).

    Fuer jeden Patch werden Hypothesen mit gleichem ``(lever, change_type)`` aggregiert; die
    Confidence wird um ``sign(delta) * weight * hyp_confidence`` je Treffer verschoben und auf
    ``[0, 1]`` geklemmt. Erwiesen positive Aenderungsarten steigen, erwiesen negative sinken.
    Deterministisch (feste Aggregationsreihenfolge, ``round(..., 6)``); **ohne Hypothesen bleibt
    jeder Patch bit-genau unveraendert** — der Sprint-3-Pfad ist damit rueckwaertskompatibel.

    Args:
        proposals: Die vom Fix-Agent erzeugten Patches (vor der Priorisierung).
        hypotheses: Aus dem Gedaechtnis abgerufene, domaingleiche Effekt-Hypothesen.
        weight: Maximaler Confidence-Hub je erwiesener Einheit (Konstante ``MEMORY_PRIOR_WEIGHT``).

    Returns:
        Die Patches mit ggf. angepasster Confidence (unveraenderte Instanzen bei kein Treffer).
    """
    if not hypotheses:
        return tuple(proposals)
    adjust: dict[tuple[Lever, ChangeType], float] = {}
    for hyp in hypotheses:
        key = (hyp.lever, hyp.change_type)
        sign = 1.0 if hyp.delta > 0 else (-1.0 if hyp.delta < 0 else 0.0)
        adjust[key] = adjust.get(key, 0.0) + sign * weight * hyp.confidence
    adjusted: list[FixProposal] = []
    for proposal in proposals:
        nudge = adjust.get((proposal.lever, proposal.change_type), 0.0)
        if nudge == 0.0:
            adjusted.append(proposal)
            continue
        new_confidence = max(0.0, min(1.0, round(proposal.confidence + nudge, 6)))
        adjusted.append(proposal.model_copy(update={"confidence": new_confidence}))
    return tuple(adjusted)
