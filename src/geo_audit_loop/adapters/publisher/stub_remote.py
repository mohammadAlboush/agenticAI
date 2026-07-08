"""Remote-Publisher-Stubs: WordPress & GitHub hinter demselben ``PublisherPort`` (opt-in).

In Sprint 3 bewusst NICHT scharf geschaltet: Der echte Schreibzugriff auf eine Live-Seite
oder ein Repo ist erst Teil eines spaeteren Meilensteins und braucht Credentials + erweiterte
Sicherheits-Reviews. Diese Stubs beweisen die Erweiterbarkeit (eine fuenfte Senke ergaenzt man,
ohne den Kern anzufassen), fuehren aber KEINEN externen Aufruf aus: Ohne ``allow_remote=True``
werfen sie ``DeployBlocked``; auch mit Flag liefern sie nur ``status=BLOCKED`` (Projektregeln §6).
Die echten SDK-Importe blieben — wenn sie spaeter kommen — in den Methoden (Lazy-Import).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from geo_audit_loop.domain.errors import DeployBlocked
from geo_audit_loop.domain.fix import ApprovalDecision, DeployResult, DeployStatus, FixPlan
from geo_audit_loop.domain.run import RunContext

_DISABLED_DETAIL = "Remote-Publishing in Sprint 3 deaktiviert (HITL-only-Meilenstein)."


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _BlockedRemotePublisher:
    """Gemeinsame Basis: partitioniert wie die anderen Adapter, schreibt aber nie extern."""

    name = "remote"

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


class WordPressPublisher(_BlockedRemotePublisher):
    """Opt-in-Stub fuer den WordPress-REST-Deploy (in Sprint 3 blockiert)."""

    name = "wordpress"


class GitHubPublisher(_BlockedRemotePublisher):
    """Opt-in-Stub fuer den GitHub-PR-Deploy (in Sprint 3 blockiert)."""

    name = "github"
