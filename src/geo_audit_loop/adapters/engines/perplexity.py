"""Engine-Adapter: Perplexity Sonar (einzige Live-Engine in Sprint 1).

POST an ``/chat/completions`` ueber einen rotierenden Proxy. Citations kommen aus
``search_results`` (Rank = 1-basierter Array-Index; KEIN ``id``-Feld) mit Fallback auf
das flache ``citations``-Array. 429/5xx werden mit Backoff erneut versucht; nicht
behebbare HTTP-Fehler werden als ``ProbeResult(status=ERROR)`` zurueckgegeben (der
Sampler entscheidet ueber Budget). Kein Streaming, ``disable_search`` wird nie gesetzt.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from geo_audit_loop.config.constants import (
    PERPLEXITY_ENDPOINT,
    RETRY_BASE_DELAY_S,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_DELAY_S,
)
from geo_audit_loop.domain.errors import EngineError
from geo_audit_loop.domain.metrics import evaluate_target
from geo_audit_loop.domain.probe import (
    Citation,
    EngineId,
    ProbeRequest,
    ProbeResult,
    ProbeStatus,
    ProbeUsage,
)
from geo_audit_loop.observability.retry import retry_call
from geo_audit_loop.ports.proxy import ProxyPort

ClientFactory = Callable[[str | None], httpx.Client]
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_DEFAULT_TIMEOUT_S = 30.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _RetryableStatus(Exception):
    """Interner Marker fuer wiederholbare HTTP-Status (429/5xx)."""


class PerplexityEngineAdapter:
    """Live-Adapter fuer die Perplexity-Sonar-API (erfuellt ``EnginePort``)."""

    def __init__(
        self,
        *,
        api_key: str | None,
        proxy: ProxyPort | None = None,
        client_factory: ClientFactory | None = None,
        max_attempts: int = RETRY_MAX_ATTEMPTS,
        base_delay_s: float = RETRY_BASE_DELAY_S,
        max_delay_s: float = RETRY_MAX_DELAY_S,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise EngineError("PERPLEXITY_API_KEY fehlt - Live-Adapter nicht nutzbar")
        self._api_key = api_key
        self._proxy = proxy
        self._client_factory = client_factory or self._default_client_factory
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._clock = clock if clock is not None else _utc_now
        self._sleep = sleep

    @property
    def engine_id(self) -> EngineId:
        """Identitaet der Engine."""
        return EngineId.PERPLEXITY

    def _default_client_factory(self, proxy: str | None) -> httpx.Client:
        return httpx.Client(proxy=proxy, timeout=_DEFAULT_TIMEOUT_S)

    def _resolve_proxy(self, request: ProbeRequest) -> str | None:
        if self._proxy is None or request.proxy_index is None:
            return None
        return self._proxy.get(request.proxy_index)

    def _body(self, request: ProbeRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt_text}],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.search_mode is not None:
            body["search_mode"] = request.search_mode.value
        return body

    def _post(self, body: dict[str, Any], proxy_url: str | None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        client = self._client_factory(proxy_url)
        try:
            response = client.post(PERPLEXITY_ENDPOINT, json=body, headers=headers)
        finally:
            client.close()
        if response.status_code in _RETRY_STATUS:
            raise _RetryableStatus(f"HTTP {response.status_code}")
        response.raise_for_status()
        return response

    def probe(self, request: ProbeRequest) -> ProbeResult:
        """Fragt Perplexity ab und liefert ein normalisiertes ``ProbeResult``."""
        proxy_url = self._resolve_proxy(request)
        body = self._body(request)
        started = time.perf_counter()
        try:
            response = retry_call(
                lambda: self._post(body, proxy_url),
                max_attempts=self._max_attempts,
                base_delay_s=self._base_delay_s,
                max_delay_s=self._max_delay_s,
                retry_on=(_RetryableStatus, httpx.TransportError),
                sleep=self._sleep,
            )
        except (httpx.HTTPError, _RetryableStatus) as exc:
            return self._error_result(request, str(exc), started)
        return self._success_result(request, response.json(), started)

    def _success_result(
        self, request: ProbeRequest, data: dict[str, Any], started: float
    ) -> ProbeResult:
        citations = _extract_citations(data)
        cited, rank = evaluate_target(citations, request.target_domain)
        answer = _extract_answer(data)
        mentioned = cited or request.target_domain.lower() in answer.lower()
        return ProbeResult(
            run_id=request.run_id,
            engine_id=EngineId.PERPLEXITY,
            model=request.model,
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            proxy_label=request.proxy_label,
            answer_text=answer,
            citations=tuple(citations),
            target_cited=cited,
            target_rank=rank,
            mentioned=mentioned,
            usage=_extract_usage(data),
            status=ProbeStatus.OK,
            probed_at=self._clock(),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _error_result(self, request: ProbeRequest, error: str, started: float) -> ProbeResult:
        return ProbeResult(
            run_id=request.run_id,
            engine_id=EngineId.PERPLEXITY,
            model=request.model,
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            proxy_label=request.proxy_label,
            status=ProbeStatus.ERROR,
            error=error,
            probed_at=self._clock(),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _extract_citations(data: dict[str, Any]) -> list[Citation]:
    results = data.get("search_results") or []
    citations: list[Citation] = []
    for item in results:
        url = item.get("url") if isinstance(item, dict) else None
        if not url:
            continue
        # Rang = 1-basierte Position ueber die TATSAECHLICH gueltigen Citations
        # (URL-lose Eintraege werden uebersprungen und zaehlen nicht mit).
        citations.append(
            Citation(
                url=url,
                engine=EngineId.PERPLEXITY,
                title=item.get("title"),
                snippet=item.get("snippet"),
                published_date=item.get("date"),
                rank=len(citations) + 1,
                raw=item,
            )
        )
    if citations:
        return citations
    # Fallback: flaches citations-Array (nur URLs), gleiche Rang-Logik
    flat: list[Citation] = []
    for url in data.get("citations") or []:
        if url:
            flat.append(Citation(url=url, engine=EngineId.PERPLEXITY, rank=len(flat) + 1))
    return flat


def _extract_answer(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return str(content) if content else ""


def _extract_usage(data: dict[str, Any]) -> ProbeUsage:
    usage = data.get("usage") or {}
    return ProbeUsage(
        prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
        completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        total_tokens=int(usage.get("total_tokens", 0) or 0),
    )
