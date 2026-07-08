"""Opt-in Live-Smoke-Test gegen die echte Anthropic-Messages-API (Web-Search-Engine).

Standardmaessig uebersprungen. Bewusst ausfuehren mit:
    GEO_RUN_LIVE_TESTS=1 ANTHROPIC_API_KEY=sk-ant-... uv run pytest -m live
"""

from __future__ import annotations

import os

import pytest

from geo_audit_loop.adapters.engines.claude import ClaudeEngineAdapter
from geo_audit_loop.config.engines import ENGINE_REGISTRY
from geo_audit_loop.domain.probe import EngineId, ProbeRequest, ProbeStatus

pytestmark = pytest.mark.live

_OPT_IN = bool(os.getenv("GEO_RUN_LIVE_TESTS")) and bool(os.getenv("ANTHROPIC_API_KEY"))


@pytest.mark.skipif(not _OPT_IN, reason="Live-Tests nur mit GEO_RUN_LIVE_TESTS=1 + API-Key")
def test_live_claude_engine_smoke() -> None:
    adapter = ClaudeEngineAdapter(api_key=os.environ["ANTHROPIC_API_KEY"])
    request = ProbeRequest(
        run_id="live-smoke",
        engine_id=EngineId.CLAUDE,
        prompt_id="p1",
        prompt_text="Was ist die NIS2-Richtlinie und wen betrifft sie?",
        prompt_version="v1",
        model=ENGINE_REGISTRY[EngineId.CLAUDE].model,
        target_domain="it-sicherheit.de",
        max_tokens=512,
        temperature=0.2,
    )
    result = adapter.probe(request)
    assert result.status is ProbeStatus.OK
    assert result.answer_text
