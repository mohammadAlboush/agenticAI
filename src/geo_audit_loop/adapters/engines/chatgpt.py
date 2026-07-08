"""Engine-Adapter: ChatGPT (OpenAI Responses API mit ``web_search``-Tool).

POST an ``/v1/responses`` ueber einen rotierenden Proxy, mit dem ``web_search``-Server-Tool.
Die Quellen kommen aus den ``url_citation``-Annotationen der Message-Output-Bloecke (jeweils
mit ``url``/``title``). 429/5xx werden mit Backoff erneut versucht; nicht behebbare HTTP-Fehler
werden als ``ProbeResult(status=ERROR)`` zurueckgegeben.

Robust geparst (``.get`` mit Defaults, Typpruefungen): variiert die Antwortform leicht, faellt
der Adapter auf leere Citations zurueck statt zu crashen.
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
_DEFAULT_TIMEOUT_S = 60.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _RetryableStatus(Exception):
    """Interner Marker fuer wiederholbare HTTP-Status (429/5xx)."""


class ChatGPTEngineAdapter:
    """Live-Adapter fuer die OpenAI-Responses-API mit Web-Suche (erfuellt ``EnginePort``)."""

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
            raise EngineError("OPENAI_API_KEY fehlt - ChatGPT-Engine-Adapter nicht nutzbar")
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
        return {
            "model": request.model,
            "input": request.prompt_text,
            "tools": [{"type": "web_search"}],
            "max_output_tokens": request.max_tokens,
        }

    def _post(self, body: dict[str, Any], proxy_url: str | None) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
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
        """Fragt ChatGPT (mit Web-Suche) ab und liefert ein normalisiertes ``ProbeResult``.

        ``probe`` wirft NIE (EnginePort-Vertrag): jeder transiente/HTTP-/Parse-Fehler wird zu
        ``ProbeResult(status=ERROR)``. Der ``try`` umschliesst Request, JSON-Decode UND das
        Parsen — ein Nicht-JSON-2xx-Body, eine kaputte Proxy-URL oder eine unerwartete
        Antwortform brechen nur die eine Zelle, nicht den Lauf.
        """
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
            return self._success_result(request, response.json(), started)
        except (httpx.HTTPError, httpx.InvalidURL, _RetryableStatus, ValueError) as exc:
            return self._error_result(request, str(exc), started)

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


def _message_content(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Sammelt alle Content-Bloecke der ``message``-Output-Items (defensiv)."""
    blocks: list[dict[str, Any]] = []
    for item in data.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "message":
            blocks.extend(b for b in (item.get("content") or []) if isinstance(b, dict))
    return blocks


def _extract_citations(data: dict[str, Any]) -> list[Citation]:
    """Baut Citations aus den ``url_citation``-Annotationen der Message-Bloecke.

    Robust gegen nicht-String url/title (ausser-spezifikations-Antwort): nur String-URLs werden
    zu Citations, nicht-String-title -> None. So wirft die Konstruktion keine ValidationError,
    die ``probe()`` verlassen wuerde (EnginePort-Vertrag).
    """
    citations: list[Citation] = []
    for block in _message_content(data):
        for ann in block.get("annotations") or []:
            if not isinstance(ann, dict) or ann.get("type") != "url_citation":
                continue
            url = ann.get("url")
            if not isinstance(url, str) or not url:
                continue
            title = ann.get("title")
            citations.append(
                Citation(
                    url=url,
                    engine=EngineId.CHATGPT,
                    title=title if isinstance(title, str) else None,
                    rank=len(citations) + 1,
                    raw=ann,
                )
            )
    return citations


def _extract_answer(data: dict[str, Any]) -> str:
    parts = [
        str(block.get("text") or "")  # None (JSON null) -> "" statt literal "None"
        for block in _message_content(data)
        if block.get("type") in ("output_text", "text")
    ]
    return "".join(parts)


def _extract_usage(data: dict[str, Any]) -> ProbeUsage:
    usage = data.get("usage") or {}
    prompt = int(usage.get("input_tokens", 0) or 0)
    completion = int(usage.get("output_tokens", 0) or 0)
    total = int(usage.get("total_tokens", 0) or 0)
    # Anzahl der Web-Suchen (fuer den Budget-Cap): jedes web_search_call-Output-Item zaehlt eine.
    searches = sum(
        1
        for item in (data.get("output") or [])
        if isinstance(item, dict) and item.get("type") == "web_search_call"
    )
    return ProbeUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total or prompt + completion,
        server_search_requests=searches or None,
    )
