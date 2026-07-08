"""Unit: SAIA-Reasoning-Adapter (httpx MockTransport, kein Netz)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from geo_audit_loop.adapters.reasoning.saia import SaiaReasoningAdapter
from geo_audit_loop.domain.errors import ReasoningError
from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningStatus

FIXED = datetime(2026, 1, 1, 12, 0, 0)
Handler = Callable[[httpx.Request], httpx.Response]
BASE_URL = "https://chat-ai.academiccloud.de/v1"


def _req(schema: dict[str, Any] | None = None) -> ReasoningRequest:
    return ReasoningRequest(
        run_id="run-1",
        task="pattern_miner",
        system="Du bist ein GEO-Analyst.",
        prompt_text="Analysiere die Top-Seiten.",
        model="openai-gpt-oss-120b",
        max_tokens=512,
        temperature=0.0,
        seed=42,
        response_schema=schema,
    )


def _adapter(handler: Handler, *, attempts: int = 3) -> SaiaReasoningAdapter:
    return SaiaReasoningAdapter(
        api_key="saia-test",
        base_url=BASE_URL,
        model="openai-gpt-oss-120b",
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=attempts,
        base_delay_s=0.0,
        max_delay_s=0.0,
        clock=lambda: FIXED,
        sleep=lambda _d: None,
    )


def _ok_payload(text: str = '{"templates": []}') -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


def test_success_returns_text_and_usage() -> None:
    adapter = _adapter(lambda _r: httpx.Response(200, json=_ok_payload()))
    result = adapter.reason(_req())
    assert result.status is ReasoningStatus.OK
    assert result.text == '{"templates": []}'
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 50
    assert result.usage.total_tokens == 150
    assert adapter.model == "openai-gpt-oss-120b"


def test_schema_lands_as_json_instruction_in_system() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_ok_payload())

    schema = {"type": "object", "properties": {"templates": {"type": "array"}}}
    _adapter(handler).reason(_req(schema))
    assert captured["model"] == "openai-gpt-oss-120b"
    assert captured["seed"] == 42
    system_msg = captured["messages"][0]
    assert system_msg["role"] == "system"
    assert "JSON-Objekt" in system_msg["content"]
    assert '"templates"' in system_msg["content"]
    assert captured["messages"][1] == {"role": "user", "content": "Analysiere die Top-Seiten."}


def test_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})
        return httpx.Response(200, json=_ok_payload())

    result = _adapter(handler).reason(_req())
    assert result.status is ReasoningStatus.OK
    assert calls["n"] == 2


def test_persistent_error_returns_error_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    result = _adapter(handler).reason(_req())
    assert result.status is ReasoningStatus.ERROR
    assert result.error is not None


def test_missing_api_key_raises() -> None:
    with pytest.raises(ReasoningError):
        SaiaReasoningAdapter(api_key=None, base_url=BASE_URL, model="m")
