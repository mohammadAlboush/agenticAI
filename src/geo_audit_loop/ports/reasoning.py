"""Port: LLM-Reasoning fuer die inhaltlichen Agenten (Pattern-Miner, GEO-Auditor)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningResult


@runtime_checkable
class ReasoningPort(Protocol):
    """Abstraktes Reasoning: nimmt einen ``ReasoningRequest``, liefert ein ``ReasoningResult``.

    Vertrag analog ``EnginePort``: transiente Fehler werden NICHT nach aussen geworfen,
    sondern als ``ReasoningResult(status=ERROR, error=...)`` zurueckgegeben (der Agent
    entscheidet ueber Retry/Abbruch). ``ReasoningError`` nur fuer nicht behebbare
    Konfigurationsfehler. Der Adapter kennt kein Budget — das erzwingt der Agent.
    """

    @property
    def model(self) -> str:
        """Das genutzte Modell (fuer Logging und Kosten-Tracking)."""
        ...

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        """Fuehrt einen einzelnen Reasoning-Aufruf aus und liefert das Ergebnis."""
        ...
