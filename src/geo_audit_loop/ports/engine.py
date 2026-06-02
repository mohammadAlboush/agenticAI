"""Port: Abfrage einer Such-/AI-Engine."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from geo_audit_loop.domain.probe import EngineId, ProbeRequest, ProbeResult


@runtime_checkable
class EnginePort(Protocol):
    """Abstrakte Engine: nimmt einen ``ProbeRequest``, liefert ein normalisiertes ``ProbeResult``.

    Vertrag: ``probe`` laesst transiente Fehler NICHT nach aussen, sondern gibt
    ``ProbeResult(status=ERROR, error=...)`` zurueck (der Sampler entscheidet ueber
    Retry und Budget). ``EngineError`` nur fuer nicht behebbare Konfigurationsfehler.
    Die Engine kennt kein Budget — das erzwingt der Sampler ueber den ``CostTracker``.
    """

    @property
    def engine_id(self) -> EngineId:
        """Identitaet der Engine (fuer Logging, Persistenz und Aggregation)."""
        ...

    def probe(self, request: ProbeRequest) -> ProbeResult:
        """Fuehrt eine einzelne Abfrage aus und liefert das normalisierte Ergebnis."""
        ...
