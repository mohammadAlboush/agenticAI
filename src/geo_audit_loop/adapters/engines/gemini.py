"""Engine-Adapter: Google Gemini mit Search-Grounding (Free-Tier-faehige Live-Engine).

POST an ``generateContent`` mit ``tools: [{"google_search": {}}]``; die Quellen kommen
aus ``groundingMetadata.groundingChunks[].web``. Deren ``uri`` ist eine Google-Redirect-
URL (vertexaisearch.cloud.google.com) — der Adapter loest sie per ``Location``-Header
in die Original-URL auf (Aufruf geht nur an Google, nie an die Zielseite); Fallback ist
die Domain aus ``web.title``. Eigen-Drosselung haelt das Free-Tier-Rate-Limit ein
(``GEMINI_MIN_INTERVAL_S``); 429/5xx werden mit Backoff erneut versucht; nicht behebbare
Fehler werden als ``ProbeResult(status=ERROR)`` zurueckgegeben.

ToS-Hinweis: Die Grounding-Ergebnisse dienen ausschliesslich der internen Forschungs-
Messung und werden nicht oeffentlich dargestellt; ``searchEntryPoint`` wird verworfen.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from functools import partial
from typing import Any

import httpx

from geo_audit_loop.config.constants import (
    GEMINI_ENDPOINT_TEMPLATE,
    GEMINI_MIN_INTERVAL_S,
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
_REDIRECT_HOST = "vertexaisearch.cloud.google.com"
_REDIRECT_CACHE_MAX = 4096  # harte Obergrenze gegen unbegrenztes Wachstum (Memory-Schutz)
# Gemini sucht mit dem google_search-Tool nur "bei Bedarf"; reine Definitionsfragen
# wuerde es aus dem Modellwissen beantworten -> keine Quellen. Diese System-Anweisung
# stosst die Websuche zuverlaessig an (naeher am Verhalten der Verbraucher-App, in der
# Gemini standardmaessig grounded). Sie aendert NICHT die geteilten Probe-Prompts.
_GROUNDING_INSTRUCTION = (
    "Beantworte die folgende Frage auf Basis einer aktuellen Google-Websuche und "
    "stuetze deine Antwort auf konkrete, auffindbare Web-Quellen."
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _RetryableStatus(Exception):
    """Interner Marker fuer wiederholbare HTTP-Status (429/5xx)."""


class GeminiEngineAdapter:
    """Live-Adapter fuer die Gemini-API mit Google-Search-Grounding (``EnginePort``)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_keys: Sequence[str] | None = None,
        proxy: ProxyPort | None = None,
        client_factory: ClientFactory | None = None,
        min_interval_s: float = GEMINI_MIN_INTERVAL_S,
        max_attempts: int = RETRY_MAX_ATTEMPTS,
        base_delay_s: float = RETRY_BASE_DELAY_S,
        max_delay_s: float = RETRY_MAX_DELAY_S,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # Mehrere Keys (verschiedene Google-Projekte) erhoehen das Free-Tier-Tageskontingent:
        # ist eins erschoepft (429), rotiert der Adapter zum naechsten.
        keys = [k for k in (list(api_keys) if api_keys else [api_key]) if k]
        if not keys:
            raise EngineError("GOOGLE_API_KEY fehlt - Gemini-Live-Adapter nicht nutzbar")
        self._keys = keys
        self._key_index = 0
        self._proxy = proxy
        self._client_factory = client_factory or self._default_client_factory
        self._min_interval_s = min_interval_s
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._clock = clock if clock is not None else _utc_now
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._redirect_cache: dict[str, str] = {}

    @property
    def engine_id(self) -> EngineId:
        """Identitaet der Engine."""
        return EngineId.GEMINI

    def _default_client_factory(self, proxy: str | None) -> httpx.Client:
        return httpx.Client(proxy=proxy, timeout=_DEFAULT_TIMEOUT_S)

    def _resolve_proxy(self, request: ProbeRequest) -> str | None:
        if self._proxy is None or request.proxy_index is None:
            return None
        return self._proxy.get(request.proxy_index)

    def _pace(self) -> None:
        """Haelt den Mindestabstand zwischen Requests ein (Free-Tier-Rate-Limit)."""
        if self._last_request_at is not None:
            wait = self._min_interval_s - (self._monotonic() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._monotonic()

    def _body(self, request: ProbeRequest) -> dict[str, Any]:
        return {
            "systemInstruction": {"parts": [{"text": _GROUNDING_INSTRUCTION}]},
            "contents": [{"parts": [{"text": request.prompt_text}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
        }

    def _post(self, client: httpx.Client, request: ProbeRequest, key: str) -> httpx.Response:
        self._pace()
        endpoint = GEMINI_ENDPOINT_TEMPLATE.format(model=request.model)
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
        response = client.post(endpoint, json=self._body(request), headers=headers)
        if response.status_code in _RETRY_STATUS:
            raise _RetryableStatus(f"HTTP {response.status_code}")
        response.raise_for_status()
        return response

    def probe(self, request: ProbeRequest) -> ProbeResult:
        """Fragt Gemini (mit Suche) ab und liefert ein normalisiertes ``ProbeResult``.

        Schlaegt ein Key dauerhaft mit 429/5xx fehl (z.B. Tageskontingent erschoepft),
        rotiert der Adapter einmalig durch die uebrigen Keys.
        """
        proxy_url = self._resolve_proxy(request)
        started = time.perf_counter()
        client = self._client_factory(proxy_url)
        last_error = "kein Key verfuegbar"
        try:
            for _ in range(len(self._keys)):
                key = self._keys[self._key_index]
                try:
                    response = retry_call(
                        partial(self._post, client, request, key),
                        max_attempts=self._max_attempts,
                        base_delay_s=self._base_delay_s,
                        max_delay_s=self._max_delay_s,
                        retry_on=(_RetryableStatus, httpx.TransportError),
                        sleep=self._sleep,
                    )
                    data = response.json()
                    citations = self._extract_citations(client, data)
                    break
                except _RetryableStatus as exc:
                    # Key erschoepft/ueberlastet -> naechsten Key versuchen.
                    last_error = str(exc)
                    self._key_index = (self._key_index + 1) % len(self._keys)
                except httpx.HTTPError as exc:
                    return self._error_result(request, str(exc), started)
            else:
                return self._error_result(request, last_error, started)
        finally:
            client.close()
        cited, rank = evaluate_target(citations, request.target_domain)
        answer = _extract_answer(data)
        mentioned = cited or request.target_domain.lower() in answer.lower()
        return ProbeResult(
            run_id=request.run_id,
            engine_id=EngineId.GEMINI,
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
            engine_id=EngineId.GEMINI,
            model=request.model,
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            proxy_label=request.proxy_label,
            status=ProbeStatus.ERROR,
            error=error,
            probed_at=self._clock(),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    # --- Grounding-Quellen -----------------------------------------------------
    def _extract_citations(self, client: httpx.Client, data: dict[str, Any]) -> list[Citation]:
        """Baut Citations aus ``groundingChunks`` (Redirect-URLs werden aufgeloest)."""
        chunks = _grounding_chunks(data)
        citations: list[Citation] = []
        for chunk in chunks:
            web = chunk.get("web") if isinstance(chunk, dict) else None
            if not isinstance(web, dict):
                continue
            uri = str(web.get("uri") or "")
            title = str(web.get("title") or "")
            url = self._resolve_citation_url(client, uri, title)
            if not url:
                continue
            citations.append(
                Citation(
                    url=url,
                    engine=EngineId.GEMINI,
                    title=title or None,
                    rank=len(citations) + 1,
                    raw=chunk,
                )
            )
        return citations

    def _resolve_citation_url(self, client: httpx.Client, uri: str, title: str) -> str | None:
        """Loest die Google-Redirect-URL in die Original-URL auf (mit Lauf-Cache).

        Fallback bei Fehlschlag: Domain aus ``web.title`` (Seiten-Zuordnung entfaellt
        dann, Domain-Treffer via ``evaluate_target`` bleibt korrekt).
        """
        if not uri:
            return f"https://{title}/" if title else None
        if _REDIRECT_HOST not in uri:
            return uri
        if uri in self._redirect_cache:
            return self._redirect_cache[uri]
        try:
            response = client.get(uri, follow_redirects=False)
            location = response.headers.get("location")
        except httpx.HTTPError:
            location = None
        resolved = location or (f"https://{title}/" if title else None)
        if resolved:
            if len(self._redirect_cache) >= _REDIRECT_CACHE_MAX:
                self._redirect_cache.clear()  # einfache Eviction: Cache ist nur Optimierung
            self._redirect_cache[uri] = resolved
        return resolved


def _grounding_chunks(data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = data.get("candidates") or []
    if not candidates or not isinstance(candidates[0], dict):
        return []
    metadata = candidates[0].get("groundingMetadata") or {}
    chunks = metadata.get("groundingChunks") or []
    return [chunk for chunk in chunks if isinstance(chunk, dict)]


def _extract_answer(data: dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates or not isinstance(candidates[0], dict):
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else None
    texts = [str(part.get("text", "")) for part in parts or [] if isinstance(part, dict)]
    return "".join(texts)


def _extract_usage(data: dict[str, Any]) -> ProbeUsage:
    usage = data.get("usageMetadata") or {}
    prompt = int(usage.get("promptTokenCount", 0) or 0)
    tool = int(usage.get("toolUsePromptTokenCount", 0) or 0)
    completion = int(usage.get("candidatesTokenCount", 0) or 0)
    total = int(usage.get("totalTokenCount", 0) or 0)
    return ProbeUsage(
        prompt_tokens=prompt + tool,
        completion_tokens=completion,
        total_tokens=total or prompt + tool + completion,
    )
