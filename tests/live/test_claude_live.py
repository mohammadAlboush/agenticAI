"""Live (opt-in): echter Claude-Reasoning-Smoke-Test.

Default geskippt. Aktivieren mit ``GEO_RUN_LIVE_TESTS=1`` + ``ANTHROPIC_API_KEY``:
    GEO_RUN_LIVE_TESTS=1 ANTHROPIC_API_KEY=sk-... uv run pytest -m live
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live

_OPT_IN = bool(os.getenv("GEO_RUN_LIVE_TESTS")) and bool(os.getenv("ANTHROPIC_API_KEY"))


@pytest.mark.skipif(
    not _OPT_IN, reason="Live-Tests nur mit GEO_RUN_LIVE_TESTS=1 + ANTHROPIC_API_KEY"
)
def test_claude_live_smoke() -> None:
    from geo_audit_loop.adapters.reasoning.claude import ClaudeReasoningAdapter
    from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningStatus

    adapter = ClaudeReasoningAdapter(
        api_key=os.environ["ANTHROPIC_API_KEY"], model="claude-sonnet-4-6"
    )
    result = adapter.reason(
        ReasoningRequest(
            run_id="live",
            task="pattern_miner",
            system="Antworte ausschliesslich mit JSON.",
            prompt_text='Gib genau {"templates": []} zurueck.',
            model="claude-sonnet-4-6",
            max_tokens=200,
            temperature=0.0,
        )
    )
    assert result.status is ReasoningStatus.OK
