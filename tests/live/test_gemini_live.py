"""Opt-in Live-Smoke-Test gegen die echte Gemini-API (Search-Grounding, Free Tier).

Standardmaessig uebersprungen. Bewusst ausfuehren mit:
    GEO_RUN_LIVE_TESTS=1 GOOGLE_API_KEY=... uv run pytest -m live
"""

from __future__ import annotations

import os

import pytest

from geo_audit_loop.adapters.engines.gemini import GeminiEngineAdapter
from geo_audit_loop.domain.probe import EngineId, ProbeRequest, ProbeStatus

pytestmark = pytest.mark.live

_OPT_IN = bool(os.getenv("GEO_RUN_LIVE_TESTS")) and bool(os.getenv("GOOGLE_API_KEY"))


@pytest.mark.skipif(not _OPT_IN, reason="Live-Tests nur mit GEO_RUN_LIVE_TESTS=1 + API-Key")
def test_live_gemini_smoke() -> None:
    adapter = GeminiEngineAdapter(api_key=os.environ["GOOGLE_API_KEY"])
    request = ProbeRequest(
        run_id="live-smoke",
        engine_id=EngineId.GEMINI,
        prompt_id="p1",
        prompt_text="Was ist die NIS2-Richtlinie und wen betrifft sie?",
        prompt_version="v1",
        model="gemini-3.5-flash",
        target_domain="it-sicherheit.de",
        max_tokens=512,
        temperature=0.2,
    )
    result = adapter.probe(request)
    assert result.status is ProbeStatus.OK
    assert result.answer_text
    # Grounding sollte Quellen liefern; aufgeloeste URLs duerfen keine Redirects mehr sein.
    assert all("vertexaisearch" not in c.url for c in result.citations)
