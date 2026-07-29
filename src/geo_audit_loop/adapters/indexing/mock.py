"""MockIndexingAdapter: deterministischer Dry-Run-Index-Kanal (Offline-Default).

Reicht NICHTS extern ein (kein I/O): jede Submission wird als ``SKIPPED`` mit
``dry_run=True`` beantwortet — der sichtbare Beweis, dass der Post-Deploy-Pfad
verdrahtet ist, ohne je einen Such-Index zu beruehren (Projektregeln §6). Die Uhr
ist injizierbar, damit Ergebnisse in Tests byte-identisch reproduzierbar sind.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from geo_audit_loop.domain.indexing import (
    EndpointResult,
    IndexingEndpoint,
    IndexSubmission,
    IndexSubmissionResult,
    IndexSubmissionStatus,
)
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.logging import get_logger, log_event

_logger = get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MockIndexingAdapter:
    """Erfuellt ``IndexingPort`` — reiner Dry-Run, kein externer Request."""

    name = "mock"

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock if clock is not None else _utc_now

    def submit(
        self, submission: IndexSubmission, *, run_context: RunContext
    ) -> IndexSubmissionResult:
        """Meldet die Submission als uebersprungen (Dry-Run), ohne etwas zu senden."""
        detail = f"Mock: {len(submission.urls)} URLs NICHT eingereicht (Dry-Run)."
        result = IndexSubmissionResult(
            run_id=submission.run_id,
            host=submission.host,
            urls=submission.urls,
            generated_at=self._clock(),
            dry_run=True,  # Mock beruehrt nie einen echten Index
            status=IndexSubmissionStatus.SKIPPED,
            endpoints=(
                EndpointResult(
                    endpoint=IndexingEndpoint.MOCK,
                    status=IndexSubmissionStatus.SKIPPED,
                    http_status=None,
                    attempts=0,
                    detail=detail,
                ),
            ),
            detail=detail,
        )
        log_event(
            _logger,
            "index_submission",
            run_id=run_context.run_id,
            agent="indexing",
            adapter=self.name,
            status=result.status.value,
            n_urls=len(submission.urls),
            dry_run=True,
        )
        return result
