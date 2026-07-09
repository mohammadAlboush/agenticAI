"""IndexNow-Adapter (Live-Loop): reicht geaenderte URLs bei api.indexnow.org ein.

POST ``{host, key, keyLocation, urlList}`` an den IndexNow-Endpunkt (erreicht
Bing/Yandex/Naver/Seznam). Vertrag des ``IndexingPort``: nach erfolgreicher
Konstruktion wirft ``submit`` NIE — jeder HTTP-/Transportfehler wird als Status im
``IndexSubmissionResult`` abgebildet. Mapping: 200/202 => SUBMITTED; 429 =>
RATE_LIMITED **terminal ohne Retry** (Wiederholen waere ein Spam-Signal an den
Index); 5xx/Transportfehler => Retry mit Backoff (``retry_call``), danach FAILED;
sonstige 4xx => FAILED ohne Retry. Der Key wird bei der Konstruktion validiert
(Laenge 8-128, sonst ``ConfigError``) und erscheint NIE in ``detail`` oder Logs —
nur in Payload und ``keyLocation``, wie vom Protokoll verlangt. Batches werden auf
das Protokoll-Limit (``INDEXNOW_MAX_URLS_PER_BATCH``) gekappt.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from geo_audit_loop.config.constants import (
    INDEXNOW_ENDPOINT,
    INDEXNOW_KEY_MAX_LEN,
    INDEXNOW_KEY_MIN_LEN,
    INDEXNOW_MAX_URLS_PER_BATCH,
    INDEXNOW_TIMEOUT_S,
    RETRY_BASE_DELAY_S,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_DELAY_S,
)
from geo_audit_loop.domain.errors import ConfigError
from geo_audit_loop.domain.indexing import (
    EndpointResult,
    IndexingEndpoint,
    IndexSubmission,
    IndexSubmissionResult,
    IndexSubmissionStatus,
)
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.logging import get_logger, log_event
from geo_audit_loop.observability.retry import retry_call

ClientFactory = Callable[[], httpx.Client]

_ACCEPTED_STATUS = frozenset({200, 202})
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR_MIN = 500
# IndexNow verlangt explizit "application/json; charset=utf-8".
_HEADERS: dict[str, str] = {"Content-Type": "application/json; charset=utf-8"}

_logger = get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _RetryableStatus(Exception):
    """Interner Marker fuer wiederholbare HTTP-Status (nur 5xx — 429 ist terminal)."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class IndexNowAdapter:
    """Live-Adapter fuer das IndexNow-Protokoll (erfuellt ``IndexingPort``)."""

    def __init__(
        self,
        *,
        key: str | None,
        key_location: str | None = None,
        client_factory: ClientFactory | None = None,
        max_attempts: int = RETRY_MAX_ATTEMPTS,
        base_delay_s: float = RETRY_BASE_DELAY_S,
        max_delay_s: float = RETRY_MAX_DELAY_S,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not key or not INDEXNOW_KEY_MIN_LEN <= len(key) <= INDEXNOW_KEY_MAX_LEN:
            raise ConfigError(
                "INDEXNOW_KEY fehlt oder hat ungueltige Laenge "
                f"(erlaubt: {INDEXNOW_KEY_MIN_LEN}-{INDEXNOW_KEY_MAX_LEN} Zeichen)"
            )
        self._key = key
        self._key_location = key_location
        self._client_factory = client_factory or self._default_client_factory
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._clock = clock if clock is not None else _utc_now
        self._sleep = sleep

    @property
    def name(self) -> str:
        """Stabiles Adapter-Label fuer Result/Logs."""
        return "indexnow"

    def _default_client_factory(self) -> httpx.Client:
        return httpx.Client(timeout=INDEXNOW_TIMEOUT_S)

    def _resolve_key_location(self, host: str) -> str:
        """Explizite Key-Location oder Protokoll-Default ``https://<host>/<key>.txt``."""
        if (
            self._key_location
        ):  # leerer String (GEO_INDEXNOW_KEY_LOCATION=) zaehlt als nicht gesetzt
            return self._key_location
        return f"https://{host}/{self._key}.txt"

    def submit(
        self, submission: IndexSubmission, *, run_context: RunContext
    ) -> IndexSubmissionResult:
        """Reicht die URLs per POST ein; Fehler werden als Status abgebildet, nie geworfen."""
        urls = submission.urls[:INDEXNOW_MAX_URLS_PER_BATCH]
        capped = len(urls) < len(submission.urls)
        payload: dict[str, Any] = {
            "host": submission.host,
            "key": self._key,
            "keyLocation": self._resolve_key_location(submission.host),
            "urlList": list(urls),
        }
        attempts = 0

        def _post_once() -> httpx.Response:
            nonlocal attempts
            attempts += 1
            client = self._client_factory()
            try:
                response = client.post(INDEXNOW_ENDPOINT, json=payload, headers=_HEADERS)
            finally:
                client.close()
            if response.status_code >= _HTTP_SERVER_ERROR_MIN:
                raise _RetryableStatus(response.status_code)
            return response

        http_status: int | None = None
        try:
            response = retry_call(
                _post_once,
                max_attempts=self._max_attempts,
                base_delay_s=self._base_delay_s,
                max_delay_s=self._max_delay_s,
                retry_on=(_RetryableStatus, httpx.TransportError),
                sleep=self._sleep,
            )
        except _RetryableStatus as exc:
            http_status = exc.status_code
            status = IndexSubmissionStatus.FAILED
            detail = f"HTTP {exc.status_code} nach {attempts} Versuchen"
        except httpx.HTTPError as exc:
            status = IndexSubmissionStatus.FAILED
            detail = f"Transportfehler nach {attempts} Versuchen: {exc.__class__.__name__}"
        else:
            http_status = response.status_code
            if response.status_code in _ACCEPTED_STATUS:
                status = IndexSubmissionStatus.SUBMITTED
                detail = f"{len(urls)} URLs eingereicht (HTTP {response.status_code})"
            elif response.status_code == _HTTP_TOO_MANY_REQUESTS:
                status = IndexSubmissionStatus.RATE_LIMITED
                detail = "HTTP 429 — terminal, kein Retry (Spam-Signal an den Index)"
            else:
                status = IndexSubmissionStatus.FAILED
                detail = f"HTTP {response.status_code} — nicht wiederholbar"
        if capped:
            detail += f"; Batch auf {INDEXNOW_MAX_URLS_PER_BATCH} URLs gekappt"

        result = IndexSubmissionResult(
            run_id=submission.run_id,
            host=submission.host,
            urls=urls,
            generated_at=self._clock(),
            dry_run=False,  # es wurde tatsaechlich extern gesendet (bzw. versucht)
            status=status,
            endpoints=(
                EndpointResult(
                    endpoint=IndexingEndpoint.INDEXNOW,
                    status=status,
                    http_status=http_status,
                    attempts=attempts,
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
            status=status.value,
            http_status=http_status,
            attempts=attempts,
            n_urls=len(urls),
            dry_run=False,
        )
        return result
