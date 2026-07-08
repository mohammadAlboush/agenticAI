"""FilesystemPublisher: schreibt freigegebene Patches als lokale Artefakte (sicherer Deploy).

Schreibt pro freigegebenem Patch eine JSON-Datei nach ``runs/<run_id>/patches/<patch_id>.json``
plus ein ``fix_plan.json``-Manifest. Das ist ein *echter* Schreibvorgang — aber ausschliesslich
ins lokale Run-Verzeichnis, NIE auf die Live-Domain (Projektregeln §6). Abgelehnte Patches werden
nicht geschrieben. So entsteht ein nachpruefbares Deploy-Artefakt ohne externes Risiko.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from geo_audit_loop.adapters.publisher import partition_by_approval
from geo_audit_loop.config import constants as c
from geo_audit_loop.domain.errors import StorageError
from geo_audit_loop.domain.fix import ApprovalDecision, DeployResult, DeployStatus, FixPlan
from geo_audit_loop.domain.run import RunContext


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FilesystemPublisher:
    """Erfuellt ``PublisherPort`` — schreibt Patch-Artefakte lokal, nie extern."""

    name = "filesystem"

    def __init__(self, runs_dir: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self._runs_dir = runs_dir
        self._clock = clock if clock is not None else _utc_now

    def publish(
        self,
        plan: FixPlan,
        decisions: Mapping[str, ApprovalDecision],
        *,
        run_context: RunContext,
        dry_run: bool = True,
    ) -> DeployResult:
        """Schreibt je freigegebenem Patch ein Artefakt; uebrige -> ``skipped_patch_ids``."""
        approved, skipped = partition_by_approval(plan.proposals, decisions)
        target = self._runs_dir / plan.run_id / c.PATCHES_SUBDIR
        try:
            if approved:  # nur schreiben, wenn es etwas Freigegebenes gibt
                target.mkdir(parents=True, exist_ok=True)
                (target / "fix_plan.json").write_text(plan.model_dump_json(indent=2), "utf-8")
                for proposal in approved:
                    (target / f"{proposal.patch_id}.json").write_text(
                        proposal.model_dump_json(indent=2), "utf-8"
                    )
        except OSError as exc:
            raise StorageError(f"Patch-Artefakt schreiben fehlgeschlagen: {exc}") from exc
        return DeployResult(
            run_id=plan.run_id,
            target_domain=plan.target_domain,
            generated_at=self._clock(),
            publisher=self.name,
            dry_run=True,  # Live-Domain unberuehrt; nur lokales Artefakt
            applied_patch_ids=tuple(p.patch_id for p in approved),
            skipped_patch_ids=tuple(p.patch_id for p in skipped),
            status=DeployStatus.APPLIED if approved else DeployStatus.DRY_RUN,
            artifact_path=str(target) if approved else None,
            detail=f"{len(approved)} Patch-Artefakt(e) lokal geschrieben (Live-Domain unberuehrt).",
        )
