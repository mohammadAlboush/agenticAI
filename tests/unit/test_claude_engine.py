"""Unit: Claude-Engine-Adapter mit Web-Search (httpx MockTransport, kein Netz)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from geo_audit_loop.adapters.engines.claude import ClaudeEngineAdapter
from geo_audit_loop.domain.errors import EngineError
from geo_audit_loop.domain.probe import EngineId, ProbeRequest, ProbeStatus

FIXED = datetime(2026, 1, 1, 12, 0, 0)
Handler = Callable[[httpx.Request], httpx.Response]


def _req() -> ProbeRequest:
    return ProbeRequest(
        run_id="run-1",
        engine_id=EngineId.CLAUDE,
        prompt_id="p1",
        prompt_text="Was ist die NIS2-Richtlinie?",
        prompt_version="v1",
        model="claude-sonnet-4-6",
        target_domain="it-sicherheit.de",
        max_tokens=256,
        temperature=0.2,
    )


def _payload() -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": "NIS2 verpflichtet Unternehmen ..."},
            {
                "type": "web_search_tool_result",
                "content": [
                    {"type": "web_search_result", "url": "https://www.bsi.bund.de/grundschutz"},
                    {
                        "type": "web_search_result",
                        "url": "https://www.it-sicherheit.de/nis2-richtlinie",
                        "title": "NIS2",
                    },
                ],
            },
        ],
        "usage": {"input_tokens": 15, "output_tokens": 20},
    }


def _adapter(handler: Handler, *, attempts: int = 3) -> ClaudeEngineAdapter:
    return ClaudeEngineAdapter(
        api_key="sk-ant-test",
        client_factory=lambda _proxy: httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=attempts,
        base_delay_s=0.0,
        max_delay_s=0.0,
        clock=lambda: FIXED,
        sleep=lambda _d: None,
    )


def test_success_extracts_web_search_citations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.anthropic.com"
        assert request.headers["anthropic-version"]
        return httpx.Response(200, json=_payload())

    result = _adapter(handler).probe(_req())
    assert result.status is ProbeStatus.OK
    assert [c.url for c in result.citations] == [
        "https://www.bsi.bund.de/grundschutz",
        "https://www.it-sicherheit.de/nis2-richtlinie",
    ]
    assert result.target_cited is True
    assert result.target_rank == 2
    assert result.usage.prompt_tokens == 15
    assert result.usage.total_tokens == 35  # input + output
    assert result.answer_text.startswith("NIS2")


def test_falls_back_to_inline_text_citations() -> None:
    payload = {
        "content": [
            {
                "type": "text",
                "text": "Siehe Quelle.",
                "citations": [
                    {
                        "type": "web_search_result_location",
                        "url": "https://www.it-sicherheit.de/nis2-richtlinie",
                        "title": "NIS2",
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 5, "output_tokens": 5},
    }
    result = _adapter(lambda _r: httpx.Response(200, json=payload)).probe(_req())
    assert result.status is ProbeStatus.OK
    assert result.citations[0].url == "https://www.it-sicherheit.de/nis2-richtlinie"
    assert result.target_cited is True


def test_request_body_contains_web_search_tool() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_payload())

    _adapter(handler).probe(_req())
    assert captured["tools"] == [{"type": "web_search_20250305", "name": "web_search"}]
    assert captured["model"] == "claude-sonnet-4-6"
    assert "temperature" not in captured  # bewusst weggelassen (400 auf neueren Modellen)


def test_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})
        return httpx.Response(200, json=_payload())

    result = _adapter(handler).probe(_req())
    assert result.status is ProbeStatus.OK
    assert calls["n"] == 2


def test_persistent_5xx_returns_error() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={})

    result = _adapter(handler, attempts=3).probe(_req())
    assert result.status is ProbeStatus.ERROR
    assert calls["n"] == 3


def test_missing_api_key_raises() -> None:
    with pytest.raises(EngineError):
        ClaudeEngineAdapter(api_key=None)


def test_non_json_body_returns_error_not_raise() -> None:
    # 2xx mit Nicht-JSON-Body (z.B. Proxy-HTML): probe() darf NICHT werfen (EnginePort-Vertrag).
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy error</html>")

    result = _adapter(handler).probe(_req())
    assert result.status is ProbeStatus.ERROR


def test_non_string_title_does_not_crash() -> None:
    # Ausser-Spezifikation: strukturierter title -> keine ValidationError; URL bleibt Citation.
    payload = {
        "content": [
            {
                "type": "web_search_tool_result",
                "content": [
                    {
                        "type": "web_search_result",
                        "url": "https://www.it-sicherheit.de/nis2-richtlinie",
                        "title": {"lang": "de", "value": "T"},
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    result = _adapter(lambda _r: httpx.Response(200, json=payload)).probe(_req())
    assert result.status is ProbeStatus.OK
    assert result.citations[0].url == "https://www.it-sicherheit.de/nis2-richtlinie"
    assert result.citations[0].title is None  # nicht-String verworfen, kein Crash


def test_usage_counts_web_search_requests_for_budget() -> None:
    # Web-Suche wird separat berechnet (usd_per_search) -> Anzahl muss in den Budget-Cap fliessen.
    payload = _payload()
    payload["usage"] = {
        "input_tokens": 10,
        "output_tokens": 5,
        "server_tool_use": {"web_search_requests": 2},
    }
    result = _adapter(lambda _r: httpx.Response(200, json=payload)).probe(_req())
    assert result.usage.server_search_requests == 2
