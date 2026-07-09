"""Publisher-Adapter (Sprint 3): wenden freigegebene Patches an (Deploy-Schritt).

Alle Adapter erfuellen ``PublisherPort`` und teilen den HITL-Filter ``partition_by_approval``:
nur Patches mit ``approved=True`` werden angewandt, der Rest landet in ``skipped_patch_ids``
(Projektregeln §6). ``MockPublisher`` ist der Default fuer die Offline-Demo (reiner Dry-Run);
``FilesystemPublisher`` schreibt sichere Patch-Artefakte lokal (nie die Live-Domain);
``wordpress`` deployt live ueber die WP-REST-API (Doppel-Gate + Backup-vor-Write);
``stub_remote`` haelt GitHub hinter demselben Port (opt-in, blockiert).
"""

from __future__ import annotations

from collections.abc import Mapping

from geo_audit_loop.domain.fix import ApprovalDecision, FixProposal, FixStatus


def partition_by_approval(
    proposals: tuple[FixProposal, ...], decisions: Mapping[str, ApprovalDecision]
) -> tuple[tuple[FixProposal, ...], tuple[FixProposal, ...]]:
    """Teilt Patches in (freigegeben, uebersprungen) — fehlende/abgelehnte Freigabe => skip.

    Das ist das in Code gegossene HITL-Gate: ein Patch wird nur dann als freigegeben
    behandelt, wenn fuer seine ``patch_id`` eine Entscheidung mit ``approved=True`` vorliegt.
    """
    approved: list[FixProposal] = []
    skipped: list[FixProposal] = []
    for proposal in proposals:
        decision = decisions.get(proposal.patch_id)
        if decision is not None and decision.approved:
            approved.append(proposal.model_copy(update={"status": FixStatus.APPLIED}))
        else:
            skipped.append(proposal.model_copy(update={"status": FixStatus.SKIPPED}))
    return tuple(approved), tuple(skipped)
