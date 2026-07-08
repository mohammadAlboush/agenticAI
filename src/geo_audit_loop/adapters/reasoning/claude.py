"""Reasoning-Adapter: Claude (Anthropic) -- die einzige Live-Reasoning-Quelle in Sprint 2.

Ruft die Messages-API auf (System + ein User-Turn), normalisiert Antworttext und
Token-Usage in ein ``ReasoningResult``. Transiente Fehler (Rate-Limit/Verbindung/5xx)
werden mit Backoff erneut versucht; nicht behebbare API-Fehler werden als
``ReasoningResult(status=ERROR)`` zurueckgegeben (der Agent entscheidet ueber Abbruch).
Der ``anthropic``-Import liegt im Modul (Live-Dependency aus ``pyproject.toml``); die
Factory laedt dieses Modul nur im Live-Pfad.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import anthropic

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

# Wiederholbare Anthropic-Fehler (transient). Nicht behebbare API-Fehler nicht erneut versuchen.
_RETRYABLE: tuple[type[Exception], ...] = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)
_DEFAULT_TIMEOUT_S = 60.0
_TOOL_NAME = "emit_result"  # erzwingt strukturierte JSON-Ausgabe (Tool-Use)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ClaudeReasoningAdapter:
    """Live-Adapter fuer Claude (Anthropic Messages-API); erfuellt ``ReasoningPort``."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        # anthropic-Client ist untypisiert hier (Any) -- bewusst, damit Tests einen Fake
        # injizieren koennen und der Adapter SDK-Versions-robust bleibt (CLAUDE.md §4).
        client: Any | None = None,
        client_factory: Callable[[], Any] | None = None,
        max_attempts: int = RETRY_MAX_ATTEMPTS,
        base_delay_s: float = RETRY_BASE_DELAY_S,
        max_delay_s: float = RETRY_MAX_DELAY_S,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if client is None and not api_key:
            raise ReasoningError("ANTHROPIC_API_KEY fehlt - Live-Reasoning nicht nutzbar")
        self._api_key = api_key
        self._model = model
        self._client = client
        self._client_factory = client_factory if client_factory is not None else self._default
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._clock = clock if clock is not None else _utc_now
        self._sleep = sleep

    @property
    def model(self) -> str:
        """Das genutzte Claude-Modell."""
        return self._model

    def _default(self) -> Any:
        return anthropic.Anthropic(api_key=self._api_key, timeout=_DEFAULT_TIMEOUT_S)

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        """Fragt Claude ab und liefert ein normalisiertes ``ReasoningResult``."""
        client = self._client if self._client is not None else self._client_factory()
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt_text}],
        }
        if request.system:
            kwargs["system"] = request.system
        if request.response_schema is not None:
            # Tool-Use erzwingt schema-konformes JSON statt Freitext -> kein Parse-Risiko.
            kwargs["tools"] = [
                {
                    "name": _TOOL_NAME,
                    "description": "Gib das Ergebnis strukturiert ueber dieses Tool zurueck.",
                    "input_schema": request.response_schema,
                }
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": _TOOL_NAME}
        started = time.perf_counter()
        try:
            response = retry_call(
                lambda: client.messages.create(**kwargs),
                max_attempts=self._max_attempts,
                base_delay_s=self._base_delay_s,
                max_delay_s=self._max_delay_s,
                retry_on=_RETRYABLE,
                sleep=self._sleep,
            )
        except anthropic.APIError as exc:
            return self._error_result(request, str(exc), started)
        return self._success_result(request, response, started)

    def _success_result(
        self, request: ReasoningRequest, response: Any, started: float
    ) -> ReasoningResult:
        return ReasoningResult(
            run_id=request.run_id,
            task=request.task,
            model=request.model,
            text=_extract_text(response),
            usage=_extract_usage(response),
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


def _extract_text(response: Any) -> str:
    """Antworttext: bevorzugt das ``tool_use``-Ergebnis als JSON, sonst Text-Bloecke."""
    parts: list[str] = []
    for block in getattr(response, "content", None) or []:
        btype = getattr(block, "type", None)
        if btype == "tool_use":
            return json.dumps(getattr(block, "input", {}) or {}, ensure_ascii=False)
        if btype == "text":
            parts.append(str(getattr(block, "text", "")))
    return "".join(parts)


def _extract_usage(response: Any) -> ReasoningUsage:
    """Liest input/output-Tokens aus ``response.usage`` (fehlertolerant)."""
    usage = getattr(response, "usage", None)
    inp = int(getattr(usage, "input_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or 0)
    return ReasoningUsage(input_tokens=inp, output_tokens=out, total_tokens=inp + out)
