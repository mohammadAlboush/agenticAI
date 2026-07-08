"""Unit: ChatGPT-Engine-Adapter (OpenAI Responses API, httpx MockTransport, kein Netz)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from geo_audit_loop.adapters.engines.chatgpt import ChatGPTEngineAdapter
from geo_audit_loop.domain.errors import EngineError
from geo_audit_loop.domain.probe import EngineId, ProbeRequest, ProbeStatus

FIXED = datetime(2026, 1, 1, 12, 0, 0)
Handler = Callable[[httpx.Request], httpx.Response]


def _req() -> ProbeRequest:
    return ProbeRequest(
        run_id="run-1",
        engine_id=EngineId.CHATGPT,
        prompt_id="p1",
        prompt_text="Was ist die NIS2-Richtlinie?",
        prompt_version="v1",
        model="gpt-4o",
        target_domain="it-sicherheit.de",
        max_tokens=256,
        temperature=0.2,
    )


def _payload() -> dict[str, Any]:
    return {
        "output": [
            {"type": "web_search_call", "status": "completed"},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "NIS2 verpflichtet Unternehmen ...",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://www.bsi.bund.de/grundschutz",
                            },
                            {
                                "type": "url_citation",
                                "url": "https://www.it-sicherheit.de/nis2-richtlinie",
                                "title": "NIS2",
                            },
                        ],
                    }
                ],
            },
        ],
        "usage": {"input_tokens": 12, "output_tokens": 18, "total_tokens": 30},
    }


def _adapter(handler: Handler, *, attempts: int = 3) -> ChatGPTEngineAdapter:
    return ChatGPTEngineAdapter(
        api_key="sk-test",
        client_factory=lambda _proxy: httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=attempts,
        base_delay_s=0.0,
        max_delay_s=0.0,
        clock=lambda: FIXED,
        sleep=lambda _d: None,
    )


def test_success_extracts_url_citations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openai.com"
        return httpx.Response(200, json=_payload())

    result = _adapter(handler).probe(_req())
    assert result.status is ProbeStatus.OK
    assert [c.url for c in result.citations] == [
        "https://www.bsi.bund.de/grundschutz",
        "https://www.it-sicherheit.de/nis2-richtlinie",
    ]
    assert result.target_cited is True
    assert result.target_rank == 2
    assert result.usage.total_tokens == 30
    assert result.answer_text.startswith("NIS2")


def test_no_annotations_yields_no_citations() -> None:
    payload = {
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "Keine Quelle."}]}
        ],
        "usage": {"input_tokens": 3, "output_tokens": 3, "total_tokens": 6},
    }
    result = _adapter(lambda _r: httpx.Response(200, json=payload)).probe(_req())
    assert result.status is ProbeStatus.OK
    assert result.citations == ()
    assert result.target_cited is False


def test_request_body_contains_web_search_tool() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_payload())

    _adapter(handler).probe(_req())
    assert captured["tools"] == [{"type": "web_search"}]
    assert captured["model"] == "gpt-4o"
    assert captured["input"].startswith("Was ist")


def test_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={})
        return httpx.Response(200, json=_payload())

    result = _adapter(handler).probe(_req())
    assert result.status is ProbeStatus.OK
    assert calls["n"] == 2


def test_persistent_5xx_returns_error() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(502, json={})

    result = _adapter(handler, attempts=3).probe(_req())
    assert result.status is ProbeStatus.ERROR
    assert calls["n"] == 3


def test_missing_api_key_raises() -> None:
    with pytest.raises(EngineError):
        ChatGPTEngineAdapter(api_key=None)


def test_non_json_body_returns_error_not_raise() -> None:
    # 2xx mit Nicht-JSON-Body (z.B. Proxy-HTML): probe() darf NICHT werfen (EnginePort-Vertrag).
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy error</html>")

    result = _adapter(handler).probe(_req())
    assert result.status is ProbeStatus.ERROR


def test_non_string_url_annotation_does_not_crash() -> None:
    # Ausser-Spezifikation: nicht-String-URL -> keine ValidationError, Annotation wird verworfen.
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "x",
                        "annotations": [
                            {"type": "url_citation", "url": 12345},
                            {
                                "type": "url_citation",
                                "url": "https://www.it-sicherheit.de/nis2-richtlinie",
                                "title": {"obj": "T"},
                            },
                        ],
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }
    result = _adapter(lambda _r: httpx.Response(200, json=payload)).probe(_req())
    assert result.status is ProbeStatus.OK
    assert [c.url for c in result.citations] == ["https://www.it-sicherheit.de/nis2-richtlinie"]
    assert result.citations[0].title is None
