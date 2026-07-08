"""Unit: Gemini-Adapter mit Search-Grounding (httpx MockTransport, kein Netz)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from geo_audit_loop.adapters.engines.gemini import GeminiEngineAdapter
from geo_audit_loop.domain.errors import EngineError
from geo_audit_loop.domain.probe import EngineId, ProbeRequest, ProbeStatus

FIXED = datetime(2026, 1, 1, 12, 0, 0)
Handler = Callable[[httpx.Request], httpx.Response]
_REDIRECT = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"


def _req() -> ProbeRequest:
    return ProbeRequest(
        run_id="run-1",
        engine_id=EngineId.GEMINI,
        prompt_id="p1",
        prompt_text="Was ist die NIS2-Richtlinie?",
        prompt_version="v1",
        model="gemini-2.5-flash",
        target_domain="it-sicherheit.de",
        max_tokens=256,
        temperature=0.2,
    )


def _payload() -> dict[str, Any]:
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": "NIS2 verpflichtet Unternehmen ..."}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": _REDIRECT + "abc", "title": "bsi.bund.de"}},
                        {"web": {"uri": _REDIRECT + "def", "title": "it-sicherheit.de"}},
                    ]
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "toolUsePromptTokenCount": 5,
            "candidatesTokenCount": 20,
            "totalTokenCount": 35,
        },
    }


def _grounded_handler(redirect_targets: dict[str, str]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(200, json=_payload())
        target = redirect_targets.get(str(request.url))
        if target is None:
            raise httpx.ConnectError("redirect down", request=request)
        return httpx.Response(302, headers={"location": target})

    return handler


def _adapter(handler: Handler, *, attempts: int = 3) -> GeminiEngineAdapter:
    return GeminiEngineAdapter(
        api_key="aiza-test",
        client_factory=lambda _proxy: httpx.Client(transport=httpx.MockTransport(handler)),
        min_interval_s=0.0,
        max_attempts=attempts,
        base_delay_s=0.0,
        max_delay_s=0.0,
        clock=lambda: FIXED,
        monotonic=lambda: 0.0,
        sleep=lambda _d: None,
    )


def test_success_resolves_redirect_urls() -> None:
    handler = _grounded_handler(
        {
            _REDIRECT + "abc": "https://www.bsi.bund.de/grundschutz",
            _REDIRECT + "def": "https://www.it-sicherheit.de/nis2-richtlinie",
        }
    )
    result = _adapter(handler).probe(_req())
    assert result.status is ProbeStatus.OK
    assert [c.url for c in result.citations] == [
        "https://www.bsi.bund.de/grundschutz",
        "https://www.it-sicherheit.de/nis2-richtlinie",
    ]
    assert result.target_cited is True
    assert result.target_rank == 2
    assert result.usage.prompt_tokens == 15  # prompt + toolUse
    assert result.usage.total_tokens == 35
    assert result.answer_text.startswith("NIS2")


def test_redirect_failure_falls_back_to_title_domain() -> None:
    handler = _grounded_handler({})  # alle Redirect-Aufloesungen schlagen fehl
    result = _adapter(handler).probe(_req())
    assert result.status is ProbeStatus.OK
    assert [c.url for c in result.citations] == [
        "https://bsi.bund.de/",
        "https://it-sicherheit.de/",
    ]
    assert result.target_cited is True  # Domain-Treffer bleibt korrekt


def test_non_redirect_uri_passes_through() -> None:
    payload = _payload()
    payload["candidates"][0]["groundingMetadata"]["groundingChunks"] = [
        {"web": {"uri": "https://www.it-sicherheit.de/direkt", "title": "it-sicherheit.de"}}
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "generativelanguage.googleapis.com"
        return httpx.Response(200, json=payload)

    result = _adapter(handler).probe(_req())
    assert result.citations[0].url == "https://www.it-sicherheit.de/direkt"


def test_pacing_sleeps_between_requests() -> None:
    sleeps: list[float] = []
    clockbox = {"t": 0.0}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _payload()
        payload["candidates"][0]["groundingMetadata"]["groundingChunks"] = []
        return httpx.Response(200, json=payload)

    adapter = GeminiEngineAdapter(
        api_key="aiza-test",
        client_factory=lambda _p: httpx.Client(transport=httpx.MockTransport(handler)),
        min_interval_s=6.5,
        base_delay_s=0.0,
        max_delay_s=0.0,
        clock=lambda: FIXED,
        monotonic=lambda: clockbox["t"],
        sleep=sleeps.append,
    )
    adapter.probe(_req())  # erster Request: kein Warten
    clockbox["t"] = 2.0
    adapter.probe(_req())  # zweiter Request nach 2s -> 4.5s warten
    assert sleeps == [pytest.approx(4.5)]


def test_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})
        payload = _payload()
        payload["candidates"][0]["groundingMetadata"]["groundingChunks"] = []
        return httpx.Response(200, json=payload)

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
        GeminiEngineAdapter(api_key=None)


def test_rotates_to_second_key_when_first_exhausted() -> None:
    seen_keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_keys.append(request.headers["x-goog-api-key"])
        if request.headers["x-goog-api-key"] == "key-a":
            return httpx.Response(429, json={})  # Kontingent erschoepft
        payload = _payload()
        payload["candidates"][0]["groundingMetadata"]["groundingChunks"] = []
        return httpx.Response(200, json=payload)

    adapter = GeminiEngineAdapter(
        api_keys=["key-a", "key-b"],
        client_factory=lambda _p: httpx.Client(transport=httpx.MockTransport(handler)),
        min_interval_s=0.0,
        max_attempts=2,
        base_delay_s=0.0,
        max_delay_s=0.0,
        clock=lambda: FIXED,
        monotonic=lambda: 0.0,
        sleep=lambda _d: None,
    )
    result = adapter.probe(_req())
    assert result.status is ProbeStatus.OK  # key-b liefert
    assert "key-a" in seen_keys and "key-b" in seen_keys


def test_request_body_contains_search_tool() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        payload = _payload()
        payload["candidates"][0]["groundingMetadata"]["groundingChunks"] = []
        return httpx.Response(200, json=payload)

    _adapter(handler).probe(_req())
    assert captured["tools"] == [{"google_search": {}}]
    assert captured["generationConfig"]["temperature"] == 0.2
    assert captured["contents"][0]["parts"][0]["text"].startswith("Was ist")
