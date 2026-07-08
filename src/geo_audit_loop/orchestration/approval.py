"""Human-in-the-Loop-Gate: erzeugt pro Patch eine ``ApprovalDecision`` (Projektregeln §6).

Der ``ApprovalGate`` ist die einzige Stelle, an der ein Patch freigegeben wird. Er ist als
Protocol injiziert, damit die Orchestrierung framework- und UI-frei bleibt: die CLI nutzt
``AutoApproveGate`` (``--approve-all``) oder einen interaktiven Gate (in der CLI-Schicht),
das Dashboard sammelt Entscheidungen asynchron ueber Buttons, Tests nutzen Auto/Reject.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from geo_audit_loop.domain.fix import ApprovalDecision, FixPlan
from geo_audit_loop.domain.run import RunContext


class ApprovalGate(Protocol):
    """Trifft die HITL-Entscheidung fuer alle Patches eines Plans."""

    def decide(self, plan: FixPlan, run_context: RunContext) -> dict[str, ApprovalDecision]:
        """Liefert je ``patch_id`` eine ``ApprovalDecision``."""
        ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _UniformGate:
    """Basis: faellt fuer alle Patches dieselbe Entscheidung (approve oder reject)."""

    def __init__(
        self,
        *,
        approved: bool,
        reviewer: str,
        note: str = "",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._approved = approved
        self._reviewer = reviewer
        self._note = note
        self._clock = clock if clock is not None else _utc_now

    def decide(self, plan: FixPlan, run_context: RunContext) -> dict[str, ApprovalDecision]:
        """Erzeugt fuer jeden Patch eine einheitliche Entscheidung."""
        decided_at = self._clock()
        return {
            p.patch_id: ApprovalDecision(
                patch_id=p.patch_id,
                run_id=run_context.run_id,
                approved=self._approved,
                reviewer=self._reviewer,
                decided_at=decided_at,
                note=self._note,
            )
            for p in plan.proposals
        }


class AutoApproveGate(_UniformGate):
    """Gibt alle Patches frei (Demo/``--approve-all``)."""

    def __init__(
        self,
        *,
        reviewer: str = "cli:--approve-all",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(approved=True, reviewer=reviewer, clock=clock)


class RejectAllGate(_UniformGate):
    """Lehnt alle Patches ab (Tests / Sicherheits-Demo: kein Deploy)."""

    def __init__(
        self,
        *,
        reviewer: str = "cli:reject-all",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(approved=False, reviewer=reviewer, note="abgelehnt", clock=clock)
