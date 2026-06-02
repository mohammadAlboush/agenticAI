"""Opt-in Live-Smoke-Test gegen die echte Perplexity-API.

Standardmaessig uebersprungen. Bewusst ausfuehren mit:
    GEO_RUN_LIVE_TESTS=1 PERPLEXITY_API_KEY=pplx-... uv run pytest -m live
"""

from __future__ import annotations

import os

import pytest

from geo_audit_loop.adapters.engines.perplexity import PerplexityEngineAdapter
from geo_audit_loop.domain.probe import EngineId, ProbeRequest, ProbeStatus, SearchMode

pytestmark = pytest.mark.live

_OPT_IN = bool(os.getenv("GEO_RUN_LIVE_TESTS")) and bool(os.getenv("PERPLEXITY_API_KEY"))


@pytest.mark.skipif(not _OPT_IN, reason="Live-Tests nur mit GEO_RUN_LIVE_TESTS=1 + API-Key")
def test_live_perplexity_smoke() -> None:
    adapter = PerplexityEngineAdapter(api_key=os.environ["PERPLEXITY_API_KEY"])
    request = ProbeRequest(
        run_id="live-smoke",
        engine_id=EngineId.PERPLEXITY,
        prompt_id="p1",
        prompt_text="Was ist die NIS2-Richtlinie und wen betrifft sie?",
        prompt_version="v1",
        model="sonar",
        target_domain="it-sicherheit.de",
        max_tokens=256,
        temperature=0.2,
        search_mode=SearchMode.WEB,
    )
    result = adapter.probe(request)
    assert result.status is ProbeStatus.OK
    assert result.answer_text
