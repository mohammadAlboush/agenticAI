"""Unit: Claude-Reasoning-Adapter mit gemocktem Client (kein Netz)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import anthropic
import httpx
import pytest

from geo_audit_loop.adapters.reasoning.claude import ClaudeReasoningAdapter
from geo_audit_loop.domain.errors import ReasoningError
from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningStatus

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _req() -> ReasoningRequest:
    return ReasoningRequest(
        run_id="r",
        task="pattern_miner",
        system="sys",
        prompt_text="x",
        model="claude-x",
        max_tokens=100,
        temperature=0.2,
    )


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Usage:
    def __init__(self) -> None:
        self.input_tokens = 12
        self.output_tokens = 8


class _Resp:
    def __init__(self) -> None:
        self.content = [_Block('{"templates": []}')]
        self.usage = _Usage()


class _OkMessages:
    def create(self, **kwargs: Any) -> _Resp:
        return _Resp()


class _OkClient:
    def __init__(self) -> None:
        self.messages = _OkMessages()


def test_success_parses_text_and_usage() -> None:
    adapter = ClaudeReasoningAdapter(
        api_key=None, model="claude-x", client=_OkClient(), clock=lambda: FIXED
    )
    result = adapter.reason(_req())
    assert result.status is ReasoningStatus.OK
    assert result.text == '{"templates": []}'
    assert result.usage.total_tokens == 20
    assert result.model == "claude-x"


def test_api_error_returns_error_result() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    class _BoomMessages:
        def create(self, **kwargs: Any) -> Any:
            raise anthropic.APIConnectionError(request=request)

    class _BoomClient:
        def __init__(self) -> None:
            self.messages = _BoomMessages()

    adapter = ClaudeReasoningAdapter(
        api_key=None,
        model="claude-x",
        client=_BoomClient(),
        max_attempts=1,
        base_delay_s=0.0,
        max_delay_s=0.0,
        sleep=lambda _d: None,
        clock=lambda: FIXED,
    )
    result = adapter.reason(_req())
    assert result.status is ReasoningStatus.ERROR
    assert result.error


def test_missing_key_and_client_raises() -> None:
    with pytest.raises(ReasoningError):
        ClaudeReasoningAdapter(api_key=None, model="claude-x")
