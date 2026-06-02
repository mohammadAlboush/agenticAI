"""Phase-5-Gate: Perplexity-Adapter (httpx MockTransport, kein Netz)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from geo_audit_loop.adapters.engines.perplexity import PerplexityEngineAdapter
from geo_audit_loop.domain.errors import EngineError
from geo_audit_loop.domain.probe import EngineId, ProbeRequest, ProbeStatus, SearchMode

FIXED = datetime(2026, 1, 1, 12, 0, 0)
Handler = Callable[[httpx.Request], httpx.Response]


def _req() -> ProbeRequest:
    return ProbeRequest(
        run_id="run-1",
        engine_id=EngineId.PERPLEXITY,
        prompt_id="p1",
        prompt_text="Was ist die NIS2-Richtlinie?",
        prompt_version="v1",
        model="sonar-pro",
        target_domain="it-sicherheit.de",
        max_tokens=256,
        temperature=0.2,
        search_mode=SearchMode.WEB,
    )


def _adapter(handler: Handler, *, attempts: int = 3) -> PerplexityEngineAdapter:
    return PerplexityEngineAdapter(
        api_key="pplx-test",
        client_factory=lambda _proxy: httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=attempts,
        base_delay_s=0.0,
        max_delay_s=0.0,
        clock=lambda: FIXED,
        sleep=lambda _d: None,
    )


def test_success_parses_search_results() -> None:
    payload = {
        "choices": [{"message": {"content": "Quelle: it-sicherheit.de erklaert NIS2."}}],
        "search_results": [
            {"url": "https://other.com/a", "title": "A"},
            {"url": "https://www.it-sicherheit.de/nis2", "title": "NIS2", "date": "2026-01-01"},
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    adapter = _adapter(lambda _r: httpx.Response(200, json=payload))
    result = adapter.probe(_req())
    assert result.status is ProbeStatus.OK
    assert len(result.citations) == 2
    assert result.target_cited is True
    assert result.target_rank == 2
    assert result.usage.total_tokens == 30
    assert result.mentioned is True


def test_fallback_to_flat_citations() -> None:
    payload = {
        "choices": [{"message": {"content": "Antwort"}}],
        "citations": ["https://www.it-sicherheit.de/x", "https://o.com/y"],
    }
    adapter = _adapter(lambda _r: httpx.Response(200, json=payload))
    result = adapter.probe(_req())
    assert len(result.citations) == 2
    assert result.target_cited is True
    assert result.target_rank == 1


def test_rank_counts_only_valid_citations() -> None:
    # search_results[0] hat keine URL -> darf den Rang der folgenden Citation nicht verschieben.
    payload = {
        "choices": [{"message": {"content": "Antwort"}}],
        "search_results": [
            {"title": "ohne url"},
            {"url": "https://www.it-sicherheit.de/nis2", "title": "NIS2"},
        ],
    }
    adapter = _adapter(lambda _r: httpx.Response(200, json=payload))
    result = adapter.probe(_req())
    assert len(result.citations) == 1
    assert result.citations[0].rank == 1
    assert result.target_cited is True
    assert result.target_rank == 1


def test_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

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


def test_missing_api_key_raises() -> None:
    with pytest.raises(EngineError):
        PerplexityEngineAdapter(api_key=None)


def test_request_body_contains_search_mode_and_model() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    _adapter(handler).probe(_req())
    assert captured["model"] == "sonar-pro"
    assert captured["search_mode"] == "web"
