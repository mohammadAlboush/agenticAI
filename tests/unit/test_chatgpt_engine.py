"""ChatGPT-Adapter (OpenAI-Responses-API): httpx MockTransport, kein Netz."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from geo_audit_loop.adapters.engines.chatgpt import ChatGptEngineAdapter
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


def _adapter(handler: Handler, *, attempts: int = 3) -> ChatGptEngineAdapter:
    return ChatGptEngineAdapter(
        api_key="sk-test",
        client_factory=lambda _proxy: httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=attempts,
        base_delay_s=0.0,
        max_delay_s=0.0,
        clock=lambda: FIXED,
        sleep=lambda _d: None,
    )


def _annotation(url: str, title: str | None = None) -> dict[str, Any]:
    return {"type": "url_citation", "url": url, "title": title, "start_index": 0, "end_index": 1}


def _message(text: str, annotations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": annotations}],
    }


def _payload(
    *,
    output: list[dict[str, Any]],
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"output": output}
    if usage is not None:
        body["usage"] = usage
    return body


def test_success_parses_url_citations() -> None:
    payload = _payload(
        output=[
            {"type": "web_search_call", "id": "ws_1", "status": "completed"},
            _message(
                "Quelle: it-sicherheit.de erklaert NIS2.",
                [
                    _annotation("https://other.com/a", "A"),
                    _annotation("https://www.it-sicherheit.de/nis2", "NIS2"),
                ],
            ),
        ],
        usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    )
    result = _adapter(lambda _r: httpx.Response(200, json=payload)).probe(_req())
    assert result.status is ProbeStatus.OK
    assert len(result.citations) == 2
    assert result.citations[0].url == "https://other.com/a"
    assert result.citations[1].title == "NIS2"
    assert result.target_cited is True
    assert result.target_rank == 2
    assert result.mentioned is True
    assert result.usage.total_tokens == 30
    assert result.answer_text.startswith("Quelle:")


def test_counts_web_search_calls_as_server_search_requests() -> None:
    payload = _payload(
        output=[
            {"type": "web_search_call", "id": "ws_1", "status": "completed"},
            {"type": "web_search_call", "id": "ws_2", "status": "completed"},
            _message("Antwort", []),
        ],
        usage={"input_tokens": 5, "output_tokens": 7},
    )
    result = _adapter(lambda _r: httpx.Response(200, json=payload)).probe(_req())
    assert result.usage.server_search_requests == 2
    # total_tokens fehlt im Payload -> Fallback input+output
    assert result.usage.total_tokens == 12


def test_dedupes_urls_and_ranks_by_first_appearance() -> None:
    payload = _payload(
        output=[
            _message(
                "Teil 1",
                [
                    _annotation("https://a.com/x", "A"),
                    _annotation("https://a.com/x", "A nochmal"),
                ],
            ),
            _message(
                "Teil 2",
                [
                    _annotation("https://b.com/y", "B"),
                    _annotation("https://a.com/x", "A dritte"),
                ],
            ),
        ]
    )
    result = _adapter(lambda _r: httpx.Response(200, json=payload)).probe(_req())
    assert [c.url for c in result.citations] == ["https://a.com/x", "https://b.com/y"]
    assert [c.rank for c in result.citations] == [1, 2]
    # Antworttext ueber mehrere message-Items hinweg konkateniert
    assert result.answer_text == "Teil 1Teil 2"


def test_ignores_non_citation_annotations_and_reasoning_items() -> None:
    payload = _payload(
        output=[
            {"type": "reasoning", "summary": []},
            _message(
                "Antwort",
                [
                    {"type": "file_citation", "file_id": "f1"},
                    _annotation("https://www.it-sicherheit.de/nis2", "NIS2"),
                ],
            ),
        ]
    )
    result = _adapter(lambda _r: httpx.Response(200, json=payload)).probe(_req())
    assert len(result.citations) == 1
    assert result.citations[0].rank == 1
    assert result.target_cited is True
    assert result.target_rank == 1
    assert result.usage.server_search_requests == 0


def test_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})
        return httpx.Response(200, json=_payload(output=[_message("ok", [])]))

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


def test_network_error_returns_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    result = _adapter(handler).probe(_req())
    assert result.status is ProbeStatus.ERROR
    assert result.error is not None


def test_non_retryable_4xx_returns_error_without_retry() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    result = _adapter(handler).probe(_req())
    assert result.status is ProbeStatus.ERROR
    assert calls["n"] == 1


def test_missing_api_key_raises() -> None:
    with pytest.raises(EngineError):
        ChatGptEngineAdapter(api_key=None)


def test_request_payload_and_headers() -> None:
    captured: dict[str, Any] = {}
    headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        headers.update(request.headers)
        return httpx.Response(200, json=_payload(output=[_message("x", [])]))

    _adapter(handler).probe(_req())
    assert captured["model"] == "gpt-4o"
    assert captured["input"] == "Was ist die NIS2-Richtlinie?"
    assert captured["tools"] == [{"type": "web_search"}]
    assert captured["max_output_tokens"] == 256
    assert captured["temperature"] == 0.2
    # Perplexity-spezifischer search_mode darf NICHT im Body landen
    assert "search_mode" not in captured
    assert headers["authorization"] == "Bearer sk-test"
