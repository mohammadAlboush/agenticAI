"""Fix-/Deploy-Contracts (Sprint 3): aus Audit-Findings abgeleitete Patches + Freigabe + Deploy.

Der GEO-Auditor liefert priorisierte ``AuditFinding``s (Was tun). Sprint 3 setzt sie um:
der Fix-Agent macht daraus konkrete ``FixProposal``s (= ``Patch``, Projektregeln §3.2),
ein Human-in-the-Loop-Gate erzeugt pro Patch eine ``ApprovalDecision``, und erst eine
Freigabe wird ueber einen ``PublisherPort`` zu einem ``DeployResult`` (Projektregeln §6:
KEIN Auto-Deploy ohne HITL). Wie die Findings sind Patches an ``Lever`` + ``PyramidLevel``
verankert und nach der Citation-Pyramide priorisierbar.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.geo import Lever, PyramidLevel, pyramid_rank


class ChangeType(StrEnum):
    """Art der vorgeschlagenen Aenderung (geschlossenes Vokabular, keine Magic Strings)."""

    INSERT_BLOCK = "insert_block"  # eigenstaendigen Antwort-/Definitionsblock einfuegen
    REWRITE_BLOCK = "rewrite_block"  # vorhandenen Auszug durch proposed_content ersetzen
    ADD_SCHEMA = "add_schema"  # JSON-LD ergaenzen (FAQPage/Author/HowTo)
    ADD_HEADING = "add_heading"  # Ueberschriften-Struktur ergaenzen/umbauen
    META_UPDATE = "meta_update"  # Title/Meta-Description/dateModified setzen


class FixStatus(StrEnum):
    """Lebenszyklus eines einzelnen Patches."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    SKIPPED = "skipped"


class DeployStatus(StrEnum):
    """Ergebnisstatus eines Deploy-Schritts."""

    DRY_RUN = "dry_run"  # Default: nichts extern geschrieben
    APPLIED = "applied"  # Artefakt geschrieben (FilesystemPublisher)
    BLOCKED = "blocked"  # HITL-Gate hat verweigert (keine Freigabe)
    FAILED = "failed"


class FixProposal(FrozenModel):
    """Ein konkreter Aenderungsvorschlag fuer eine Flop-Seite (= ``Patch``, vor HITL).

    Traegt die Herkunft (``finding_id`` -> ``AuditFinding``), den verankerten Hebel +
    Pyramide-Ebene, die Art der Aenderung, den neuen Inhalt und eine Begruendung. Die
    ``patch_id`` ist deterministisch abgeleitet (nicht zufaellig), damit der Fingerprint
    bit-genau reproduzierbar bleibt.
    """

    patch_id: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)  # Provenienz zum AuditFinding
    target_url: str = Field(min_length=1)
    lever: Lever
    pyramid_level: PyramidLevel
    change_type: ChangeType
    current_excerpt: str = ""  # zitierter Ist-Auszug (leer bei INSERT/ADD_SCHEMA)
    proposed_content: str = Field(min_length=1)  # neuer/geaenderter Inhalt bzw. JSON-LD
    unified_diff: str = ""  # optionaler Textdiff fuer Render/Audit
    rationale: str = Field(min_length=1)  # warum das das Finding behebt (Template-Bezug)
    confidence: float = Field(ge=0.0, le=1.0)
    template_id: str | None = None  # orientierendes Template (Patch -> Hebel -> Template)
    status: FixStatus = FixStatus.PROPOSED

    @model_validator(mode="after")
    def _excerpt_required_for_rewrite(self) -> Self:
        """``rewrite_block`` ohne ``current_excerpt`` waere nicht anwendbar/nachpruefbar."""
        if self.change_type is ChangeType.REWRITE_BLOCK and not self.current_excerpt:
            raise ValueError("rewrite_block braucht current_excerpt")
        return self


class FixPlan(FrozenModel):
    """Ergebnis des Fix-Agents: die priorisierten Patches ueber die Flop-Seiten."""

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    generated_at: datetime
    prompt_version: str = Field(min_length=1)  # welche fix_agent.vN den Plan erzeugte
    proposals: tuple[FixProposal, ...] = ()


class ApprovalDecision(FrozenModel):
    """Human-in-the-Loop-Entscheidung fuer genau einen Patch (Projektregeln §6)."""

    patch_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    approved: bool
    reviewer: str = Field(min_length=1)  # z.B. "cli:--approve-all" oder "dashboard"
    decided_at: datetime
    note: str = ""


class DeployResult(FrozenModel):
    """Was wurde wo (nicht) angewandt (Projektregeln §3.2). Default: sicherer Dry-Run."""

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    generated_at: datetime
    publisher: str = Field(min_length=1)  # "mock" | "filesystem" | "wordpress" | "github"
    dry_run: bool = True  # Default SICHER: kein echter externer Write
    applied_patch_ids: tuple[str, ...] = ()
    skipped_patch_ids: tuple[str, ...] = ()  # nicht freigegeben -> uebersprungen
    status: DeployStatus = DeployStatus.DRY_RUN
    artifact_path: str | None = None  # runs/<run_id>/patches/... (Filesystem)
    artifact_ref: str | None = None  # Commit-/PR-/Post-Referenz (Remote-Stubs)
    detail: str = ""


def derive_patch_id(finding_id: str, change_type: ChangeType) -> str:
    """Deterministische Patch-ID aus Finding + Aenderungsart (kein Zufall => reproduzierbar)."""
    return f"px-{finding_id}-{change_type.value}"


def prioritize_proposals(proposals: Iterable[FixProposal]) -> tuple[FixProposal, ...]:
    """Sortiert Patches: untere Pyramide-Ebene zuerst, dann hoehere Konfidenz (geo-strategy)."""
    return tuple(
        sorted(
            proposals,
            key=lambda p: (
                pyramid_rank(p.pyramid_level),
                -p.confidence,
                p.target_url,
                p.patch_id,
            ),
        )
    )
