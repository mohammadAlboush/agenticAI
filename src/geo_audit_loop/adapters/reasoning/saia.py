"""Reasoning-Adapter: SAIA/KISSKI (GWDG Academic Cloud) -- kostenloses Hochschul-LLM.

OpenAI-kompatible ``/chat/completions``-API (Bearer-Key) via httpx, kein SDK noetig.
Da SAIA-Modelle kein erzwungenes Tool-Use-Schema garantieren, wird ein angefordertes
``response_schema`` als strikte JSON-Anweisung in die System-Message gelegt; die
Agenten validieren und wiederholen ohnehin (max. 2 Versuche, ``extract_json_object``
toleriert Codeblock-Zaeune). Transiente Fehler (429/5xx/Transport) werden mit Backoff
erneut versucht; nicht behebbare Fehler als ``ReasoningResult(status=ERROR)``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from geo_audit_loop.config.constants import (
    RETRY_BASE_DELAY_S,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_DELAY_S,
)
from geo_audit_loop.domain.errors import ReasoningError
from geo_audit_loop.domain.reasoning import (
    ReasoningRequest,
    ReasoningResult,
    ReasoningStatus,
    ReasoningUsage,
)
from geo_audit_loop.observability.retry import retry_call

ClientFactory = Callable[[], httpx.Client]
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_DEFAULT_TIMEOUT_S = 120.0  # grosse Modelle + lange Prompts -> grosszuegig

_SCHEMA_INSTRUCTION = (
    "\n\nAntworte AUSSCHLIESSLICH mit einem einzigen gueltigen JSON-Objekt, das exakt "
    "dem folgenden JSON-Schema entspricht. Kein Text davor oder danach, keine "
    "Markdown-Zaeune:\n{schema}"
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _RetryableStatus(Exception):
    """Interner Marker fuer wiederholbare HTTP-Status (429/5xx)."""


class SaiaReasoningAdapter:
    """Live-Adapter fuer den SAIA-/KISSKI-LLM-Dienst (erfuellt ``ReasoningPort``)."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model: str,
        client_factory: ClientFactory | None = None,
        max_attempts: int = RETRY_MAX_ATTEMPTS,
        base_delay_s: float = RETRY_BASE_DELAY_S,
        max_delay_s: float = RETRY_MAX_DELAY_S,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ReasoningError("SAIA_API_KEY fehlt - Hochschul-Reasoning nicht nutzbar")
        self._api_key = api_key
        self._endpoint = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._client_factory = client_factory or self._default_client_factory
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._clock = clock if clock is not None else _utc_now
        self._sleep = sleep

    @property
    def model(self) -> str:
        """Das genutzte SAIA-Modell (opaker Vendor-String)."""
        return self._model

    def _default_client_factory(self) -> httpx.Client:
        return httpx.Client(timeout=_DEFAULT_TIMEOUT_S)

    def _body(self, request: ReasoningRequest) -> dict[str, Any]:
        system = request.system
        if request.response_schema is not None:
            system += _SCHEMA_INSTRUCTION.format(
                schema=json.dumps(request.response_schema, ensure_ascii=False)
            )
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": request.prompt_text})
        body: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.seed is not None:
            body["seed"] = request.seed
        return body

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        client = self._client_factory()
        try:
            response = client.post(self._endpoint, json=body, headers=headers)
        finally:
            client.close()
        if response.status_code in _RETRY_STATUS:
            raise _RetryableStatus(f"HTTP {response.status_code}")
        response.raise_for_status()
        return response

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        """Fragt SAIA ab und liefert ein normalisiertes ``ReasoningResult``."""
        body = self._body(request)
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
        data = response.json()
        return ReasoningResult(
            run_id=request.run_id,
            task=request.task,
            model=request.model,
            text=_extract_text(data),
            usage=_extract_usage(data),
            status=ReasoningStatus.OK,
            generated_at=self._clock(),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _error_result(
        self, request: ReasoningRequest, error: str, started: float
    ) -> ReasoningResult:
        return ReasoningResult(
            run_id=request.run_id,
            task=request.task,
            model=request.model,
            status=ReasoningStatus.ERROR,
            error=error,
            generated_at=self._clock(),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _extract_text(data: dict[str, Any]) -> str:
    """Antworttext aus ``choices[0].message.content`` (fehlertolerant)."""
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return str(content) if content else ""


def _extract_usage(data: dict[str, Any]) -> ReasoningUsage:
    """Token-Verbrauch aus dem OpenAI-kompatiblen ``usage``-Block."""
    usage = data.get("usage") or {}
    inp = int(usage.get("prompt_tokens", 0) or 0)
    out = int(usage.get("completion_tokens", 0) or 0)
    total = int(usage.get("total_tokens", 0) or 0)
    return ReasoningUsage(input_tokens=inp, output_tokens=out, total_tokens=total or inp + out)
