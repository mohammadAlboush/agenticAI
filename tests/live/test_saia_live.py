"""Opt-in Live-Smoke-Test gegen den SAIA-/KISSKI-Dienst (Hochschul-LLM).

Standardmaessig uebersprungen. Bewusst ausfuehren mit:
    GEO_RUN_LIVE_TESTS=1 SAIA_API_KEY=... uv run pytest -m live
"""

from __future__ import annotations

import os

import pytest

from geo_audit_loop.adapters.reasoning.saia import SaiaReasoningAdapter
from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningStatus

pytestmark = pytest.mark.live

# Key beim Modul-Import cachen: die autouse-Env-Scrub-Fixture (tests/conftest.py)
# loescht projekteigene Variablen VOR dem Testkoerper (Muster test_serper_live.py).
_API_KEY = os.getenv("SAIA_API_KEY")
_MODEL = os.getenv("GEO_SAIA_MODEL", "openai-gpt-oss-120b")
_BASE_URL = os.getenv("GEO_SAIA_BASE_URL", "https://chat-ai.academiccloud.de/v1")
_OPT_IN = bool(os.getenv("GEO_RUN_LIVE_TESTS")) and bool(_API_KEY)


@pytest.mark.skipif(not _OPT_IN, reason="Live-Tests nur mit GEO_RUN_LIVE_TESTS=1 + API-Key")
def test_live_saia_smoke() -> None:
    model = _MODEL
    adapter = SaiaReasoningAdapter(
        api_key=_API_KEY,
        base_url=_BASE_URL,
        model=model,
    )
    request = ReasoningRequest(
        run_id="live-smoke",
        task="smoke",
        system="Du bist ein praeziser Assistent.",
        prompt_text='Antworte mit JSON: {"ok": true}',
        model=model,
        max_tokens=64,
        temperature=0.0,
        response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
    )
    result = adapter.reason(request)
    assert result.status is ReasoningStatus.OK
    assert "ok" in result.text
