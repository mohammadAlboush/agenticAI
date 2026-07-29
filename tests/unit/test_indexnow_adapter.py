"""IndexNow-/Mock-Indexing-Adapter (httpx MockTransport, kein Netz — Projektregeln §5)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from geo_audit_loop.adapters.indexing.indexnow import IndexNowAdapter
from geo_audit_loop.adapters.indexing.mock import MockIndexingAdapter
from geo_audit_loop.config.constants import INDEXNOW_ENDPOINT, INDEXNOW_MAX_URLS_PER_BATCH
from geo_audit_loop.domain.errors import ConfigError
from geo_audit_loop.domain.indexing import (
    IndexingEndpoint,
    IndexSubmission,
    IndexSubmissionStatus,
)
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.ports.indexing import IndexingPort

FIXED = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
KEY = "test-indexnow-key-0001"
Handler = Callable[[httpx.Request], httpx.Response]


def _submission(urls: tuple[str, ...] | None = None) -> IndexSubmission:
    return IndexSubmission(
        run_id="run-1",
        host="it-sicherheit.de",
        urls=urls
        if urls is not None
        else (
            "https://it-sicherheit.de/blog/nis2",
            "https://it-sicherheit.de/ratgeber/phishing",
        ),
        reason="deploy:applied:2-urls",
    )


def _run_context() -> RunContext:
    return RunContext(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        started_at=FIXED,
        seed=42,
        prompt_set_version="v1",
        config_hash="cfg-hash",
    )


def _adapter(
    handler: Handler, *, attempts: int = 3, key_location: str | None = None
) -> IndexNowAdapter:
    return IndexNowAdapter(
        key=KEY,
        key_location=key_location,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=attempts,
        base_delay_s=0.0,
        max_delay_s=0.0,
        clock=lambda: FIXED,
        sleep=lambda _d: None,
    )


# --- Erfolg: 200/202 => SUBMITTED ---


@pytest.mark.parametrize("status_code", [200, 202])
def test_accepted_status_maps_to_submitted(status_code: int) -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status_code)

    result = _adapter(handler).submit(_submission(), run_context=_run_context())
    assert result.status is IndexSubmissionStatus.SUBMITTED
    assert result.dry_run is False
    assert result.generated_at == FIXED
    assert calls["n"] == 1
    (endpoint,) = result.endpoints
    assert endpoint.endpoint is IndexingEndpoint.INDEXNOW
    assert endpoint.status is IndexSubmissionStatus.SUBMITTED
    assert endpoint.http_status == status_code
    assert endpoint.attempts == 1


# --- 429: terminal, KEIN Retry (Spam-Signal) ---


def test_429_is_terminal_without_retry() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429)

    result = _adapter(handler, attempts=3).submit(_submission(), run_context=_run_context())
    assert result.status is IndexSubmissionStatus.RATE_LIMITED
    assert calls["n"] == 1  # beweist: kein Retry-Spam an den Index
    (endpoint,) = result.endpoints
    assert endpoint.http_status == 429
    assert endpoint.attempts == 1
    assert KEY not in result.detail
    assert KEY not in endpoint.detail


# --- 5xx/Transport: Retry mit Backoff, dann FAILED ---


def test_persistent_5xx_retries_then_failed() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    result = _adapter(handler, attempts=3).submit(_submission(), run_context=_run_context())
    assert result.status is IndexSubmissionStatus.FAILED
    assert calls["n"] == 3
    (endpoint,) = result.endpoints
    assert endpoint.http_status == 500
    assert endpoint.attempts == 3


def test_5xx_then_success_recovers() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200)

    result = _adapter(handler).submit(_submission(), run_context=_run_context())
    assert result.status is IndexSubmissionStatus.SUBMITTED
    assert calls["n"] == 2
    assert result.endpoints[0].attempts == 2


def test_transport_error_retries_then_failed() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=request)

    result = _adapter(handler, attempts=3).submit(_submission(), run_context=_run_context())
    assert result.status is IndexSubmissionStatus.FAILED
    assert calls["n"] == 3
    (endpoint,) = result.endpoints
    assert endpoint.http_status is None
    assert endpoint.attempts == 3
    assert KEY not in result.detail
    assert KEY not in endpoint.detail


def test_other_4xx_is_failed_without_retry() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403)

    result = _adapter(handler, attempts=3).submit(_submission(), run_context=_run_context())
    assert result.status is IndexSubmissionStatus.FAILED
    assert calls["n"] == 1
    assert result.endpoints[0].http_status == 403


# --- Payload-Korrektheit ---


def test_payload_contains_host_key_keylocation_and_urls() -> None:
    captured: dict[str, object] = {}
    headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        headers.update({"content-type": request.headers["Content-Type"]})
        assert str(request.url) == INDEXNOW_ENDPOINT
        return httpx.Response(200)

    _adapter(handler).submit(_submission(), run_context=_run_context())
    assert captured["host"] == "it-sicherheit.de"
    assert captured["key"] == KEY
    assert captured["keyLocation"] == f"https://it-sicherheit.de/{KEY}.txt"
    assert captured["urlList"] == [
        "https://it-sicherheit.de/blog/nis2",
        "https://it-sicherheit.de/ratgeber/phishing",
    ]
    assert headers["content-type"] == "application/json; charset=utf-8"


def test_explicit_key_location_is_used_verbatim() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200)

    adapter = _adapter(handler, key_location="https://cdn.example.com/proof.txt")
    adapter.submit(_submission(), run_context=_run_context())
    assert captured["keyLocation"] == "https://cdn.example.com/proof.txt"


def test_batch_is_capped_at_protocol_limit() -> None:
    urls = tuple(
        f"https://it-sicherheit.de/p{i:05d}" for i in range(INDEXNOW_MAX_URLS_PER_BATCH + 1)
    )
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200)

    result = _adapter(handler).submit(_submission(urls=urls), run_context=_run_context())
    url_list = captured["urlList"]
    assert isinstance(url_list, list)
    assert len(url_list) == INDEXNOW_MAX_URLS_PER_BATCH
    assert len(result.urls) == INDEXNOW_MAX_URLS_PER_BATCH
    assert "gekappt" in result.detail


# --- Key-Validierung (Konstruktion) ---


@pytest.mark.parametrize("bad_key", [None, "", "kurz123", "x" * 129])
def test_invalid_key_raises_config_error(bad_key: str | None) -> None:
    with pytest.raises(ConfigError):
        IndexNowAdapter(key=bad_key)


@pytest.mark.parametrize("good_key", ["a" * 8, "b" * 128])
def test_key_length_boundaries_are_accepted(good_key: str) -> None:
    adapter = IndexNowAdapter(key=good_key)
    assert adapter.name == "indexnow"


# --- Mock-Adapter: deterministisch, kein I/O ---


def test_mock_is_deterministic_skipped_dry_run() -> None:
    adapter = MockIndexingAdapter(clock=lambda: FIXED)
    first = adapter.submit(_submission(), run_context=_run_context())
    second = adapter.submit(_submission(), run_context=_run_context())
    assert first == second  # byte-identisch reproduzierbar
    assert first.status is IndexSubmissionStatus.SKIPPED
    assert first.dry_run is True
    assert first.generated_at == FIXED
    assert first.urls == _submission().urls
    (endpoint,) = first.endpoints
    assert endpoint.endpoint is IndexingEndpoint.MOCK
    assert endpoint.status is IndexSubmissionStatus.SKIPPED
    assert endpoint.attempts == 0


# --- Port-Konformitaet ---


def test_adapters_satisfy_indexing_port() -> None:
    def offline_client() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))

    assert isinstance(MockIndexingAdapter(), IndexingPort)
    assert isinstance(IndexNowAdapter(key=KEY, client_factory=offline_client), IndexingPort)
