"""Engine-Adapter: Claude (Anthropic Messages API mit Web-Search-Server-Tool).

POST an ``/v1/messages`` ueber einen rotierenden Proxy, mit dem Web-Search-Server-Tool
(``web_search_20250305`` — Basis-Variante, modell-agnostisch). Die Quellen kommen aus den
``web_search_tool_result``-Bloecken (jeweils ``web_search_result`` mit ``url``/``title``);
Fallback sind die Inline-``citations`` der Text-Bloecke. 429/5xx werden mit Backoff erneut
versucht; nicht behebbare HTTP-Fehler werden als ``ProbeResult(status=ERROR)`` zurueckgegeben.

Die ``temperature`` wird bewusst NICHT gesendet: auf neueren Modellen (Sonnet 5, Opus 4.8/4.7,
Fable 5) ist der Sampling-Parameter entfernt und wuerde 400en — Weglassen ist auf jedem Modell
gueltig, und Web-Suche ist ohnehin nicht deterministisch.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from geo_audit_loop.config.constants import (
    ANTHROPIC_ENDPOINT,
    ANTHROPIC_VERSION,
    ANTHROPIC_WEB_SEARCH_TOOL_TYPE,
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
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504, 529})
_DEFAULT_TIMEOUT_S = 60.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _RetryableStatus(Exception):
    """Interner Marker fuer wiederholbare HTTP-Status (429/5xx/529)."""


class ClaudeEngineAdapter:
    """Live-Adapter fuer die Anthropic-Messages-API mit Web-Search (erfuellt ``EnginePort``)."""

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
            raise EngineError("ANTHROPIC_API_KEY fehlt - Claude-Engine-Adapter nicht nutzbar")
        # Das Modell kommt pro Probe aus ``request.model`` (aus der Engine-Registry, wie bei den
        # uebrigen Adaptern) — kein redundanter Konstruktor-Parameter.
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
        return EngineId.CLAUDE

    def _default_client_factory(self, proxy: str | None) -> httpx.Client:
        return httpx.Client(proxy=proxy, timeout=_DEFAULT_TIMEOUT_S)

    def _resolve_proxy(self, request: ProbeRequest) -> str | None:
        if self._proxy is None or request.proxy_index is None:
            return None
        return self._proxy.get(request.proxy_index)

    def _body(self, request: ProbeRequest) -> dict[str, Any]:
        return {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": "user", "content": request.prompt_text}],
            "tools": [{"type": ANTHROPIC_WEB_SEARCH_TOOL_TYPE, "name": "web_search"}],
        }

    def _post(self, body: dict[str, Any], proxy_url: str | None) -> httpx.Response:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        client = self._client_factory(proxy_url)
        try:
            response = client.post(ANTHROPIC_ENDPOINT, json=body, headers=headers)
        finally:
            client.close()
        if response.status_code in _RETRY_STATUS:
            raise _RetryableStatus(f"HTTP {response.status_code}")
        response.raise_for_status()
        return response

    def probe(self, request: ProbeRequest) -> ProbeResult:
        """Fragt Claude (mit Web-Suche) ab und liefert ein normalisiertes ``ProbeResult``.

        ``probe`` wirft NIE (EnginePort-Vertrag): jeder transiente/HTTP-/Parse-Fehler wird zu
        ``ProbeResult(status=ERROR)``. Der ``try`` umschliesst deshalb Request, JSON-Decode UND
        das Parsen — ein Nicht-JSON-2xx-Body (Proxy-Interstitial), eine kaputte Proxy-URL oder
        eine unerwartete Antwortform brechen nur die eine Zelle, nicht den Lauf.
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
            engine_id=EngineId.CLAUDE,
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
            engine_id=EngineId.CLAUDE,
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
    """Baut Citations aus ``web_search_tool_result``-Bloecken; Fallback: Inline-Text-Citations."""
    blocks = data.get("content") or []
    citations: list[Citation] = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
            continue
        for item in block.get("content") or []:
            if not isinstance(item, dict) or item.get("type") != "web_search_result":
                continue
            _append_citation(citations, item.get("url"), item.get("title"), item)
    if citations:
        return citations
    # Fallback: Inline-Zitate der Text-Bloecke (web_search_result_location).
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        for cite in block.get("citations") or []:
            if isinstance(cite, dict):
                _append_citation(citations, cite.get("url"), cite.get("title"), cite)
    return citations


def _append_citation(
    citations: list[Citation], url: object, title: object, raw: dict[str, Any]
) -> None:
    """Fuegt eine Citation hinzu — nur bei String-URL; nicht-String-Werte crashen nicht.

    Robust gegen eine ausser-spezifikations-Antwort (z.B. strukturierter/nicht-String title):
    ``Citation.url``/``title`` sind ``str``-typisiert und wuerden im Pydantic-Lax-Modus eine
    ValidationError werfen — wir koerzieren/verwerfen stattdessen.
    """
    if not isinstance(url, str) or not url:
        return
    citations.append(
        Citation(
            url=url,
            engine=EngineId.CLAUDE,
            title=title if isinstance(title, str) else None,
            rank=len(citations) + 1,
            raw=raw,
        )
    )


def _extract_answer(data: dict[str, Any]) -> str:
    parts = [
        str(block.get("text") or "")  # None (JSON null) -> "" statt literal "None"
        for block in (data.get("content") or [])
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "".join(parts)


def _extract_usage(data: dict[str, Any]) -> ProbeUsage:
    usage = data.get("usage") or {}
    prompt = int(usage.get("input_tokens", 0) or 0)
    completion = int(usage.get("output_tokens", 0) or 0)
    # Web-Suche wird separat berechnet (usd_per_search): die Anzahl aus server_tool_use
    # in den Budget-Cap einspeisen, sonst bleibt der Such-Kostenanteil unsichtbar (§6).
    tool = usage.get("server_tool_use")
    searches = tool.get("web_search_requests") if isinstance(tool, dict) else None
    return ProbeUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        server_search_requests=int(searches) if isinstance(searches, int) else None,
    )
