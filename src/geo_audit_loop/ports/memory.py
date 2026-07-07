"""Port: das Gedaechtnis des Lern-Loops (Projektregeln §8).

Der ``MemoryPort`` hat **genau zwei** Operationen: ``store`` (eine ``EffectHypothesis``
persistieren) und ``retrieve`` (fuer einen ``MemoryQuery``-Kontext die relevanten
Hypothesen liefern). Der Agenten-Kern haengt nur an diesem Port; konkrete Adapter
(deterministisches SQLite-Mock, Chroma/bge-m3 live) werden von aussen injiziert und sind
im Test durch ein Fake ersetzbar.

**Harte Invariante:** ``retrieve`` darf nur Hypothesen der in ``MemoryQuery.target_domain``
genannten Domain zurueckgeben (Domain-Isolation — Lernen leckt nicht zwischen Domains).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from geo_audit_loop.domain.effect import EffectHypothesis
from geo_audit_loop.domain.memory import MemoryQuery


@runtime_checkable
class MemoryPort(Protocol):
    """Abstraktes Gedaechtnis fuer Effekt-Hypothesen (Implementierung: SQLite-Mock / Chroma)."""

    def store(self, hypothesis: EffectHypothesis) -> None:
        """Persistiert eine Hypothese idempotent (Upsert ueber ``hypothesis_id``)."""
        ...

    def retrieve(self, context: MemoryQuery) -> list[EffectHypothesis]:
        """Liefert die zum Kontext passenden Hypothesen (domaingefiltert, gerankt, ``top_k``)."""
        ...
