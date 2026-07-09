"""WP-B-Gate: Serper-Adapter (httpx MockTransport, kein Netz)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from geo_audit_loop.adapters.serp.serper import SerperSerpAdapter
from geo_audit_loop.domain.errors import ConfigError
from geo_audit_loop.domain.probe import ProbeStatus
from geo_audit_loop.domain.serp import SerpProvider, SerpQuery, SerpRequest

FIXED = datetime(2026, 1, 1, 12, 0, 0)
Handler = Callable[[httpx.Request], httpx.Response]


def _req(top_k: int = 10) -> SerpRequest:
    query = SerpQuery(query_id="q01", text="NIS2 Richtlinie Anforderungen", prompt_id="p01")
    return SerpRequest(run_id="run-1", query=query, top_k=top_k)


def _adapter(handler: Handler, *, attempts: int = 3) -> SerperSerpAdapter:
    return SerperSerpAdapter(
        api_key="serper-test",
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=attempts,
        base_delay_s=0.0,
        max_delay_s=0.0,
        clock=lambda: FIXED,
        sleep=lambda _d: None,
    )


def _payload() -> dict[str, Any]:
    return {
        "organic": [
            {
                "link": "https://www.bsi.bund.de/nis2",
                "position": 1,
                "title": "NIS2 beim BSI",
                "snippet": "Ueberblick zur Richtlinie.",
            },
            {"link": "https://www.it-sicherheit.de/nis2-richtlinie", "position": 2},
        ]
    }


def test_success_parses_organic_entries() -> None:
    adapter = _adapter(lambda _r: httpx.Response(200, json=_payload()))
    result = adapter.search(_req())
    assert adapter.provider is SerpProvider.SERPER
    assert result.status is ProbeStatus.OK
    assert result.run_id == "run-1"
    assert result.query_id == "q01"
    assert result.prompt_id == "p01"
    assert result.fetched_at == FIXED
    assert [e.url for e in result.entries] == [
        "https://www.bsi.bund.de/nis2",
        "https://www.it-sicherheit.de/nis2-richtlinie",
    ]
    assert [e.position for e in result.entries] == [1, 2]
    assert result.entries[0].title == "NIS2 beim BSI"
    assert result.entries[0].snippet == "Ueberblick zur Richtlinie."
    assert result.entries[1].title is None


def test_request_body_and_api_key_header() -> None:
    captured: dict[str, Any] = {}
    headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        headers.update(request.headers)
        return httpx.Response(200, json=_payload())

    _adapter(handler).search(_req(top_k=7))
    assert captured == {"q": "NIS2 Richtlinie Anforderungen", "gl": "de", "hl": "de", "num": 7}
    assert headers["x-api-key"] == "serper-test"


def test_entries_capped_to_top_k_and_skip_missing_link() -> None:
    payload = {
        "organic": [
            {"title": "ohne link"},  # wird uebersprungen, verschiebt keine Position
            {"link": "https://a.example/1"},  # ohne position-Feld -> Fallback 1
            {"link": "https://a.example/2", "position": 5},
            {"link": "https://a.example/3", "position": 6},
        ]
    }
    adapter = _adapter(lambda _r: httpx.Response(200, json=payload))
    result = adapter.search(_req(top_k=2))
    assert [e.url for e in result.entries] == ["https://a.example/1", "https://a.example/2"]
    assert [e.position for e in result.entries] == [1, 5]


def test_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})
        return httpx.Response(200, json=_payload())

    result = _adapter(handler).search(_req())
    assert result.status is ProbeStatus.OK
    assert calls["n"] == 2


def test_persistent_5xx_returns_error_result() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={})

    result = _adapter(handler, attempts=3).search(_req())
    assert result.status is ProbeStatus.ERROR
    assert result.error is not None
    assert result.entries == ()
    assert calls["n"] == 3


def test_network_error_returns_error_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    result = _adapter(handler).search(_req())
    assert result.status is ProbeStatus.ERROR
    assert result.error is not None


def test_non_retryable_http_error_returns_error_result() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403, json={"message": "forbidden"})

    result = _adapter(handler).search(_req())
    assert result.status is ProbeStatus.ERROR
    assert calls["n"] == 1  # 403 ist terminal, kein Retry


def test_missing_api_key_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        SerperSerpAdapter(api_key=None)
    with pytest.raises(ConfigError):
        SerperSerpAdapter(api_key="")
