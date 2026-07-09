"""Port: Einreichen geaenderter URLs bei Suchmaschinen-Indexen (IndexNow, Live-Loop).

Der ``IndexingPort`` ist die abstrakte Aussenwelt fuer den Post-Deploy-Schritt: er
nimmt eine ``IndexSubmission`` und liefert ein ``IndexSubmissionResult``.

**Vertrag (Muster ``EnginePort``):** ``submit`` laesst HTTP-/Transportfehler NICHT als
Exception nach aussen, sondern bildet sie auf ``status=FAILED``/``RATE_LIMITED`` im
Ergebnis ab — eine fehlgeschlagene Index-Einreichung darf den Run niemals abbrechen.
Nur nicht behebbare Konfigurationsfehler (z.B. ungueltiger Key) werfen ``ConfigError``
bereits bei der Konstruktion des Adapters.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from geo_audit_loop.domain.indexing import IndexSubmission, IndexSubmissionResult
from geo_audit_loop.domain.run import RunContext


@runtime_checkable
class IndexingPort(Protocol):
    """Abstrakter Index-Kanal (Implementierungen: Mock, IndexNow)."""

    @property
    def name(self) -> str:
        """Stabiles Label des Adapters (z.B. ``mock``, ``indexnow``) fuer Result/Logs."""
        ...

    def submit(
        self, submission: IndexSubmission, *, run_context: RunContext
    ) -> IndexSubmissionResult:
        """Reicht die URLs ein; HTTP-Fehler werden als Status abgebildet, nie geworfen."""
        ...
