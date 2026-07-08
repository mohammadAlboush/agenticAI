"""MockPublisher: deterministischer Dry-Run-Deploy (Default fuer Offline-Demo/Evals).

Wendet nichts extern an. Er partitioniert die Patches in freigegeben/uebersprungen und
meldet das als ``DeployResult`` mit ``status=DRY_RUN`` — der sichtbare Beweis, dass der
Loop geschlossen ist, ohne je eine Live-Seite zu beruehren (Projektregeln §6).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from geo_audit_loop.adapters.publisher import partition_by_approval
from geo_audit_loop.domain.fix import ApprovalDecision, DeployResult, DeployStatus, FixPlan
from geo_audit_loop.domain.run import RunContext


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MockPublisher:
    """Erfuellt ``PublisherPort`` — reiner Dry-Run, kein I/O."""

    name = "mock"

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock if clock is not None else _utc_now

    def publish(
        self,
        plan: FixPlan,
        decisions: Mapping[str, ApprovalDecision],
        *,
        run_context: RunContext,
        dry_run: bool = True,
    ) -> DeployResult:
        """Meldet, welche freigegebenen Patches angewandt WUERDEN (ohne externen Write)."""
        approved, skipped = partition_by_approval(plan.proposals, decisions)
        return DeployResult(
            run_id=plan.run_id,
            target_domain=plan.target_domain,
            generated_at=self._clock(),
            publisher=self.name,
            dry_run=True,  # Mock beruehrt nie eine Live-Seite
            applied_patch_ids=tuple(p.patch_id for p in approved),
            skipped_patch_ids=tuple(p.patch_id for p in skipped),
            status=DeployStatus.DRY_RUN,
            detail=f"Dry-Run: {len(approved)} freigegeben, {len(skipped)} uebersprungen.",
        )
