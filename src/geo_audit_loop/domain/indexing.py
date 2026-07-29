"""Indexing-Contracts (Live-Loop): Einreichen geaenderter URLs bei Suchmaschinen-Indexen.

Nach einem ECHTEN Deploy (WordPress, non-dry-run) sollen die geaenderten URLs per
IndexNow bei Bing/Yandex/Naver/Seznam eingereicht werden — das fehlende Glied zwischen
Deploy und Re-Probe. Kern-Sicherheitsentscheidung: ``build_index_submission`` liefert
NUR bei ``DeployStatus.APPLIED`` und ``dry_run=False`` eine Submission (hartes Gate im
Contract). Der Offline-Golden-Pfad (Mock/Filesystem, immer Dry-Run) kann strukturell
nie eine Index-Einreichung ausloesen. Das Ergebnis geht bewusst NICHT in den
Report-Fingerprint ein (laufvariabel, wie ``DeployResult``).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.fix import DeployResult, DeployStatus, FixPlan


class IndexingEndpoint(StrEnum):
    """Ziel-Index, bei dem URLs eingereicht werden (geschlossenes Vokabular)."""

    INDEXNOW = "indexnow"  # api.indexnow.org (Bing/Yandex/Naver/Seznam)
    BING_WEBMASTER = "bing_webmaster"  # reserviert (Bing URL Submission API)
    MOCK = "mock"  # deterministischer Test-/Offline-Endpunkt


class IndexSubmissionStatus(StrEnum):
    """Ergebnisstatus einer Index-Einreichung (je Endpunkt und aggregiert)."""

    SUBMITTED = "submitted"  # 200/202 — vom Index angenommen
    SKIPPED = "skipped"  # nicht versucht (Dry-Run, kein Opt-in, keine URLs)
    RATE_LIMITED = "rate_limited"  # 429 — terminal, KEIN Retry (Spam-Signal)
    FAILED = "failed"  # 5xx/Transportfehler nach Retries


class IndexSubmission(FrozenModel):
    """Auftrag an den ``IndexingPort``: diese URLs eines Hosts einreichen.

    ``urls`` sind Vertragsbestandteil dedupliziert UND aufsteigend sortiert
    (deterministische Batches, idempotente Wiederholung). Die URLs bleiben
    unveraendert wie publiziert — IndexNow verlangt die tatsaechliche URL,
    keine normalisierte Variante.
    """

    run_id: str = Field(min_length=1)
    host: str = Field(min_length=1)  # Site-Host, z.B. "it-sicherheit.de"
    urls: tuple[str, ...] = Field(min_length=1)
    reason: str = Field(min_length=1)  # Provenienz, z.B. "deploy:applied:2-patches"

    @model_validator(mode="after")
    def _urls_deduped_and_sorted(self) -> Self:
        """Haerte des Contracts: unsortierte oder doppelte URLs sind ein Producer-Bug."""
        if list(self.urls) != sorted(set(self.urls)):
            raise ValueError("urls muessen dedupliziert und aufsteigend sortiert sein")
        return self


class EndpointResult(FrozenModel):
    """Ergebnis der Einreichung bei genau einem Endpunkt."""

    endpoint: IndexingEndpoint
    status: IndexSubmissionStatus
    http_status: int | None = None  # letzter HTTP-Status (None bei Transportfehler/Skip)
    attempts: int = Field(default=0, ge=0)  # tatsaechlich gesendete Requests
    detail: str = ""  # menschenlesbar, NIEMALS der Key selbst


class IndexSubmissionResult(FrozenModel):
    """Aggregiertes Ergebnis einer Index-Einreichung (Rueckgabe des ``IndexingPort``).

    Default SICHER: ``dry_run=True`` + ``SKIPPED`` — ohne explizites Gegenteil wurde
    nichts extern gesendet. Geht NICHT in den Report-Fingerprint ein (laufvariabel).
    """

    run_id: str = Field(min_length=1)
    host: str = Field(min_length=1)
    urls: tuple[str, ...] = ()
    generated_at: datetime
    dry_run: bool = True  # Default SICHER: kein echter externer Request
    status: IndexSubmissionStatus = IndexSubmissionStatus.SKIPPED
    endpoints: tuple[EndpointResult, ...] = ()
    detail: str = ""


def build_index_submission(plan: FixPlan, deploy: DeployResult) -> IndexSubmission | None:
    """Leitet aus Fix-Plan + Deploy-Ergebnis die einzureichenden URLs ab (oder ``None``).

    Hartes Gate im Contract (Projektregeln §6): NUR wenn der Deploy wirklich angewandt
    wurde (``status=APPLIED`` UND ``dry_run=False``) entsteht eine Submission — der
    Offline-/Dry-Run-Pfad liefert strukturell immer ``None``. Eingereicht werden die
    ``target_url``s der tatsaechlich angewandten Patches, dedupliziert und sortiert.

    Args:
        plan: Der Fix-Plan des Runs (traegt die Patch -> URL-Zuordnung).
        deploy: Das Deploy-Ergebnis (traegt Status, Dry-Run-Flag und applied_patch_ids).

    Returns:
        Eine ``IndexSubmission`` oder ``None``, wenn nichts einzureichen ist.
    """
    if deploy.status is not DeployStatus.APPLIED or deploy.dry_run:
        return None
    applied_ids = set(deploy.applied_patch_ids)
    urls = sorted({p.target_url.strip() for p in plan.proposals if p.patch_id in applied_ids})
    if not urls:
        return None
    host = deploy.target_domain.strip().lower().lstrip(".")
    host = host[4:] if host.startswith("www.") else host
    return IndexSubmission(
        run_id=deploy.run_id,
        host=host,
        urls=tuple(urls),
        reason=f"deploy:applied:{len(urls)}-urls",
    )
