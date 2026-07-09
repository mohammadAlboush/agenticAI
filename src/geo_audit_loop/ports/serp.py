"""Port: Abfrage klassischer Suchergebnisse (SERP) fuer den Overlap-Vergleich.

Der ``SerpPort`` ist die abstrakte Aussenwelt fuer die Google-Top-K-Messung
(Implementierungen: Mock, Serper.dev).

**Vertrag (Muster ``EnginePort``):** ``search`` laesst transiente Fehler NICHT nach
aussen, sondern liefert ``SerpResult(status=ERROR, error=...)`` — der Aufrufer
entscheidet ueber Fortsetzung und Quota. Der Adapter kennt kein Budget; das erzwingt
der SERP-Sampler ueber ``CostTracker.ensure_can_request(provider)``. ``ConfigError``
nur fuer nicht behebbare Konfigurationsfehler bei der Konstruktion.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from geo_audit_loop.domain.serp import SerpProvider, SerpRequest, SerpResult


@runtime_checkable
class SerpPort(Protocol):
    """Abstrakte SERP-Quelle: nimmt einen ``SerpRequest``, liefert ein ``SerpResult``."""

    @property
    def provider(self) -> SerpProvider:
        """Identitaet der SERP-Quelle (fuer Persistenz-Schluessel, Quota und Logs)."""
        ...

    def search(self, request: SerpRequest) -> SerpResult:
        """Fuehrt eine SERP-Abfrage aus; transiente Fehler -> ``status=ERROR``-Ergebnis."""
        ...
