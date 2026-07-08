"""Port: Anwenden freigegebener Patches (Deploy-Schritt, Sprint 3).

Der ``PublisherPort`` ist die abstrakte Aussenwelt fuer den Deploy: er nimmt einen
``FixPlan`` plus die Human-in-the-Loop-Entscheidungen und liefert ein ``DeployResult``.

**Harte Invariante (Projektregeln §6):** Jeder Patch, dessen ``ApprovalDecision`` fehlt
oder ``approved=False`` ist, MUSS in ``skipped_patch_ids`` landen und darf NICHT angewandt
werden. Das ist das in Code gegossene HITL-Gate — die Orchestrierung erzwingt es zusaetzlich
(Defense in Depth), aber der Port-Vertrag macht es pro Adapter testbar.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from geo_audit_loop.domain.fix import ApprovalDecision, DeployResult, FixPlan
from geo_audit_loop.domain.run import RunContext


@runtime_checkable
class PublisherPort(Protocol):
    """Abstrakter Deploy-Kanal (Implementierungen: Mock, Filesystem, Remote-Stubs)."""

    @property
    def name(self) -> str:
        """Stabiles Label des Publishers (z.B. ``mock``), fuer DeployResult/Logs."""
        ...

    def publish(
        self,
        plan: FixPlan,
        decisions: Mapping[str, ApprovalDecision],
        *,
        run_context: RunContext,
        dry_run: bool = True,
    ) -> DeployResult:
        """Wendet ausschliesslich freigegebene Patches an; uebrige -> ``skipped_patch_ids``."""
        ...
