"""SERP-Adapter: Serper.dev (google.serper.dev) — Live-Quelle der Google-Top-K.

POST an ``/search`` mit ``X-API-KEY``-Header und Body ``q``/``gl``/``hl``/``num``.
``organic[]`` wird zu ``RankEntry``s normalisiert (``link``/``position``/``title``/
``snippet``). Kein Proxy — Serper ist ein regulaerer API-Dienst, keine Engine-Probe.
429/5xx werden mit Backoff erneut versucht; nicht behebbare Fehler werden als
``SerpResult(status=ERROR)`` zurueckgegeben (der SERP-Sampler entscheidet ueber
Fortsetzung und Quota). Fehlender API-Key -> ``ConfigError`` bei der Konstruktion.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from geo_audit_loop.config.constants import (
    RETRY_BASE_DELAY_S,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_DELAY_S,
    SERPER_ENDPOINT,
)
from geo_audit_loop.domain.errors import ConfigError
from geo_audit_loop.domain.probe import ProbeStatus
from geo_audit_loop.domain.serp import RankEntry, SerpProvider, SerpRequest, SerpResult
from geo_audit_loop.observability.retry import retry_call

ClientFactory = Callable[[], httpx.Client]
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_DEFAULT_TIMEOUT_S = 30.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _RetryableStatus(Exception):
    """Interner Marker fuer wiederholbare HTTP-Status (429/5xx)."""


class SerperSerpAdapter:
    """Live-Adapter fuer die Serper.dev-Such-API (erfuellt ``SerpPort``)."""

    def __init__(
        self,
        *,
        api_key: str | None,
        client_factory: ClientFactory | None = None,
        max_attempts: int = RETRY_MAX_ATTEMPTS,
        base_delay_s: float = RETRY_BASE_DELAY_S,
        max_delay_s: float = RETRY_MAX_DELAY_S,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ConfigError("SERPER_API_KEY fehlt - Serper-Adapter nicht nutzbar")
        self._api_key = api_key
        self._client_factory = client_factory or self._default_client_factory
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._clock = clock if clock is not None else _utc_now
        self._sleep = sleep

    @property
    def provider(self) -> SerpProvider:
        """Identitaet der SERP-Quelle."""
        return SerpProvider.SERPER

    def _default_client_factory(self) -> httpx.Client:
        return httpx.Client(timeout=_DEFAULT_TIMEOUT_S)

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        headers = {"X-API-KEY": self._api_key, "Content-Type": "application/json"}
        client = self._client_factory()
        try:
            response = client.post(SERPER_ENDPOINT, json=body, headers=headers)
        finally:
            client.close()
        if response.status_code in _RETRY_STATUS:
            raise _RetryableStatus(f"HTTP {response.status_code}")
        response.raise_for_status()
        return response

    def search(self, request: SerpRequest) -> SerpResult:
        """Fragt Serper.dev ab und liefert ein normalisiertes ``SerpResult``."""
        body: dict[str, Any] = {
            "q": request.query.text,
            "gl": request.gl,
            "hl": request.hl,
            "num": request.top_k,
        }
        started = time.perf_counter()
        try:
            response = retry_call(
                lambda: self._post(body),
                max_attempts=self._max_attempts,
                base_delay_s=self._base_delay_s,
                max_delay_s=self._max_delay_s,
                retry_on=(_RetryableStatus, httpx.TransportError),
                sleep=self._sleep,
            )
        except (httpx.HTTPError, _RetryableStatus) as exc:
            return self._error_result(request, str(exc), started)
        try:
            data = response.json()
        except ValueError as exc:
            return self._error_result(request, f"non-JSON response: {exc}", started)
        return self._success_result(request, data, started)

    def _success_result(
        self, request: SerpRequest, data: dict[str, Any], started: float
    ) -> SerpResult:
        return SerpResult(
            run_id=request.run_id,
            provider=SerpProvider.SERPER,
            query_id=request.query.query_id,
            prompt_id=request.query.prompt_id,
            query_text=request.query.text,
            entries=_extract_entries(data, request.top_k),
            status=ProbeStatus.OK,
            fetched_at=self._clock(),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _error_result(self, request: SerpRequest, error: str, started: float) -> SerpResult:
        return SerpResult(
            run_id=request.run_id,
            provider=SerpProvider.SERPER,
            query_id=request.query.query_id,
            prompt_id=request.query.prompt_id,
            query_text=request.query.text,
            status=ProbeStatus.ERROR,
            error=error,
            fetched_at=self._clock(),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _extract_entries(data: dict[str, Any], top_k: int) -> tuple[RankEntry, ...]:
    """Normalisiert ``organic[]`` zu ``RankEntry``s (max. ``top_k``, URL-lose Eintraege raus).

    ``position`` kommt bevorzugt aus der API-Antwort; fehlt sie, wird die 1-basierte
    Position ueber die TATSAECHLICH gueltigen Treffer vergeben (Muster Perplexity-Ranks).
    """
    entries: list[RankEntry] = []
    for item in data.get("organic") or []:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        if not link:
            continue
        raw_position = item.get("position")
        position = (
            raw_position
            if isinstance(raw_position, int) and raw_position >= 1
            else len(entries) + 1
        )
        entries.append(
            RankEntry(
                url=str(link),
                position=position,
                title=item.get("title"),
                snippet=item.get("snippet"),
            )
        )
        if len(entries) >= top_k:
            break
    return tuple(entries)
