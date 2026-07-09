"""Engine-Adapter: ChatGPT ueber die OpenAI-Responses-API mit Web-Search-Tool.

POST an ``/v1/responses`` direkt via httpx (bewusst NICHT das openai-SDK — Konsistenz
mit ``perplexity.py``/``gemini.py``: ClientFactory-Injection, ``retry_call`` mit Backoff,
injizierbare clock/sleep, Proxy via ``proxy_url``). Das ``web_search``-Tool liefert
Quellen als ``url_citation``-Annotations in den ``output_text``-Bloecken; der Rang ist
die Reihenfolge des ersten Auftretens, doppelte URLs werden dedupliziert. Die Anzahl
der ``web_search_call``-Items fliesst als ``ProbeUsage.server_search_requests`` in das
Kosten-Tracking (``usd_per_search`` in ``config/pricing.py``). 429/5xx werden mit
Backoff erneut versucht; nicht behebbare Fehler werden als ``ProbeResult(status=ERROR)``
zurueckgegeben (nie Exception nach Konstruktion).

Kostenwarnung: Jede Probe kann mehrere bezahlte Web-Suchen ausloesen — die volle
60-Zellen-Teilmatrix (5 IPs x 12 Prompts) liegt bei ~$2 und kollidiert mit
``DEFAULT_MAX_USD=2.0``. Live-Nutzung nur opt-in mit bewusst erhoehtem Cap.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from geo_audit_loop.config.constants import (
    OPENAI_RESPONSES_ENDPOINT,
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
# Web-Suche + Antwortgenerierung dauern zusammen laenger als ein reiner Chat-Call.
_DEFAULT_TIMEOUT_S = 60.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _RetryableStatus(Exception):
    """Interner Marker fuer wiederholbare HTTP-Status (429/5xx)."""


class ChatGptEngineAdapter:
    """Live-Adapter fuer die OpenAI-Responses-API mit ``web_search`` (``EnginePort``)."""

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
            raise EngineError("OPENAI_API_KEY fehlt - ChatGPT-Live-Adapter nicht nutzbar")
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
        return EngineId.CHATGPT

    def _default_client_factory(self, proxy: str | None) -> httpx.Client:
        return httpx.Client(proxy=proxy, timeout=_DEFAULT_TIMEOUT_S)

    def _resolve_proxy(self, request: ProbeRequest) -> str | None:
        if self._proxy is None or request.proxy_index is None:
            return None
        return self._proxy.get(request.proxy_index)

    def _body(self, request: ProbeRequest) -> dict[str, Any]:
        # search_mode ist Perplexity-spezifisch und wird hier bewusst ignoriert.
        return {
            "model": request.model,
            "input": request.prompt_text,
            "tools": [{"type": "web_search"}],
            "max_output_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

    def _post(self, body: dict[str, Any], proxy_url: str | None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        client = self._client_factory(proxy_url)
        try:
            response = client.post(OPENAI_RESPONSES_ENDPOINT, json=body, headers=headers)
        finally:
            client.close()
        if response.status_code in _RETRY_STATUS:
            raise _RetryableStatus(f"HTTP {response.status_code}")
        response.raise_for_status()
        return response

    def probe(self, request: ProbeRequest) -> ProbeResult:
        """Fragt die Responses-API ab und liefert ein normalisiertes ``ProbeResult``."""
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
        try:
            data = response.json()
        except ValueError as exc:
            return self._error_result(request, f"non-JSON response: {exc}", started)
        return self._success_result(request, data, started)

    def _success_result(
        self, request: ProbeRequest, data: dict[str, Any], started: float
    ) -> ProbeResult:
        citations = _extract_citations(data)
        cited, rank = evaluate_target(citations, request.target_domain)
        answer = _extract_answer(data)
        mentioned = cited or request.target_domain.lower() in answer.lower()
        return ProbeResult(
            run_id=request.run_id,
            engine_id=EngineId.CHATGPT,
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
            engine_id=EngineId.CHATGPT,
            model=request.model,
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            proxy_label=request.proxy_label,
            status=ProbeStatus.ERROR,
            error=error,
            probed_at=self._clock(),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _output_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Liefert die ``output``-Items der Responses-API als Dict-Liste."""
    items = data.get("output") or []
    return [item for item in items if isinstance(item, dict)]


def _text_blocks(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Liefert alle ``output_text``-Bloecke aus den ``message``-Items (in Reihenfolge)."""
    blocks: list[dict[str, Any]] = []
    for item in _output_items(data):
        if item.get("type") != "message":
            continue
        content = item.get("content") or []
        blocks.extend(
            block
            for block in content
            if isinstance(block, dict) and block.get("type") == "output_text"
        )
    return blocks


def _extract_citations(data: dict[str, Any]) -> list[Citation]:
    """Baut Citations aus ``url_citation``-Annotations (Rang = erstes Auftreten).

    Dieselbe URL kann in einer Antwort mehrfach annotiert sein — sie zaehlt nur beim
    ersten Auftreten (Dedupe per URL, Rang-Logik wie ``perplexity._extract_citations``).
    """
    citations: list[Citation] = []
    seen: set[str] = set()
    for block in _text_blocks(data):
        for annotation in block.get("annotations") or []:
            if not isinstance(annotation, dict) or annotation.get("type") != "url_citation":
                continue
            url = annotation.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            citations.append(
                Citation(
                    url=url,
                    engine=EngineId.CHATGPT,
                    title=annotation.get("title"),
                    rank=len(citations) + 1,
                    raw=annotation,
                )
            )
    return citations


def _count_web_search_calls(data: dict[str, Any]) -> int:
    """Zaehlt die ``web_search_call``-Items (bezahlte Suchen, speist den USD-Cap)."""
    return sum(1 for item in _output_items(data) if item.get("type") == "web_search_call")


def _extract_answer(data: dict[str, Any]) -> str:
    return "".join(str(block.get("text") or "") for block in _text_blocks(data))


def _extract_usage(data: dict[str, Any]) -> ProbeUsage:
    usage = data.get("usage") or {}
    prompt = int(usage.get("input_tokens", 0) or 0)
    completion = int(usage.get("output_tokens", 0) or 0)
    total = int(usage.get("total_tokens", 0) or 0)
    return ProbeUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total or prompt + completion,
        server_search_requests=_count_web_search_calls(data),
    )
