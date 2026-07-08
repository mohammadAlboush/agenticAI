"""Interaktives Human-in-the-Loop-Gate fuer die CLI (rich-Prompt je Patch).

Liegt bewusst in der CLI-Schicht (nicht in ``orchestration``): es macht echtes Terminal-I/O.
Ohne TTY (Pipe/CI) faellt es auf Ablehnung zurueck — sicherer Default, kein versehentlicher
Deploy (Projektregeln §6). Fuer die nicht-interaktive Demo nutzt man ``--approve-all``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime

from rich.console import Console
from rich.prompt import Confirm

from geo_audit_loop.domain.fix import ApprovalDecision, FixPlan
from geo_audit_loop.domain.run import RunContext


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InteractiveApproveGate:
    """Fragt pro Patch im Terminal nach Freigabe (rich ``Confirm``)."""

    def __init__(self, console: Console, *, clock: Callable[[], datetime] | None = None) -> None:
        self._console = console
        self._clock = clock if clock is not None else _utc_now

    def decide(self, plan: FixPlan, run_context: RunContext) -> dict[str, ApprovalDecision]:
        """Holt je Patch eine Freigabe-Entscheidung; ohne TTY werden alle abgelehnt."""
        interactive = sys.stdin is not None and sys.stdin.isatty()
        decisions: dict[str, ApprovalDecision] = {}
        for patch in plan.proposals:
            if interactive:
                approved = Confirm.ask(
                    f"[bold]{patch.patch_id}[/] ({patch.target_url}) freigeben?",
                    default=True,
                    console=self._console,
                )
            else:
                approved = False  # kein TTY -> sicherer Default: nicht deployen
            decisions[patch.patch_id] = ApprovalDecision(
                patch_id=patch.patch_id,
                run_id=run_context.run_id,
                approved=approved,
                reviewer="cli:interactive",
                decided_at=self._clock(),
            )
        return decisions
