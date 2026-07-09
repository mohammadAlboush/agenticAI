"""Remote-Publisher-Stub: GitHub hinter demselben ``PublisherPort`` (opt-in, blockiert).

Der echte PR-Deploy auf ein Repo ist Teil eines spaeteren Meilensteins und braucht
Credentials + erweiterte Sicherheits-Reviews. Dieser Stub beweist die Erweiterbarkeit
(eine weitere Senke ergaenzt man, ohne den Kern anzufassen), fuehrt aber KEINEN externen
Aufruf aus: Ohne ``allow_remote=True`` wirft er ``DeployBlocked``; auch mit Flag liefert
er nur ``status=BLOCKED`` (Projektregeln §6). WordPress hat inzwischen einen echten
Adapter (``adapters/publisher/wordpress.py``) und ist hier bewusst KEIN Stub mehr.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from geo_audit_loop.domain.errors import DeployBlocked
from geo_audit_loop.domain.fix import ApprovalDecision, DeployResult, DeployStatus, FixPlan
from geo_audit_loop.domain.run import RunContext

_DISABLED_DETAIL = "Remote-Publishing (GitHub-PR-Deploy) noch deaktiviert (spaeterer Meilenstein)."


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GitHubPublisher:
    """Opt-in-Stub fuer den GitHub-PR-Deploy: erfuellt den Port, schreibt aber nie extern."""

    name = "github"

    def __init__(
        self, *, allow_remote: bool = False, clock: Callable[[], datetime] | None = None
    ) -> None:
        self._allow_remote = allow_remote
        self._clock = clock if clock is not None else _utc_now

    def publish(
        self,
        plan: FixPlan,
        decisions: Mapping[str, ApprovalDecision],
        *,
        run_context: RunContext,
        dry_run: bool = True,
    ) -> DeployResult:
        """Blockiert: ohne ``allow_remote`` Fehler, sonst ``status=BLOCKED`` ohne externen Write."""
        if not self._allow_remote:
            raise DeployBlocked(f"{self.name}: {_DISABLED_DETAIL}")
        return DeployResult(
            run_id=plan.run_id,
            target_domain=plan.target_domain,
            generated_at=self._clock(),
            publisher=self.name,
            dry_run=True,
            applied_patch_ids=(),  # nichts angewandt
            skipped_patch_ids=tuple(p.patch_id for p in plan.proposals),
            status=DeployStatus.BLOCKED,
            detail=_DISABLED_DETAIL,
        )
