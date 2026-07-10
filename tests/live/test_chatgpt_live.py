"""Opt-in Live-Smoke-Test gegen die echte OpenAI-Responses-API (web_search-Tool).

Standardmaessig uebersprungen. Bewusst ausfuehren mit:
    GEO_RUN_LIVE_TESTS=1 OPENAI_API_KEY=... uv run pytest -m live

Kostenhinweis: Jede ausgeloeste Web-Suche kostet extra (usd_per_search in
config/pricing.py) — dieser Smoke-Test macht genau EINE Probe.
"""

from __future__ import annotations

import os

import pytest

from geo_audit_loop.adapters.engines.chatgpt import ChatGptEngineAdapter
from geo_audit_loop.domain.probe import EngineId, ProbeRequest, ProbeStatus

pytestmark = pytest.mark.live

# Key beim Modul-Import cachen: die autouse-Env-Scrub-Fixture (tests/conftest.py)
# loescht projekteigene Variablen VOR dem Testkoerper (Muster test_serper_live.py).
_API_KEY = os.getenv("OPENAI_API_KEY")
_OPT_IN = bool(os.getenv("GEO_RUN_LIVE_TESTS")) and bool(_API_KEY)


@pytest.mark.skipif(not _OPT_IN, reason="Live-Tests nur mit GEO_RUN_LIVE_TESTS=1 + API-Key")
def test_live_chatgpt_smoke() -> None:
    adapter = ChatGptEngineAdapter(api_key=_API_KEY)
    request = ProbeRequest(
        run_id="live-smoke",
        engine_id=EngineId.CHATGPT,
        prompt_id="p1",
        prompt_text="Was ist die NIS2-Richtlinie und wen betrifft sie?",
        prompt_version="v1",
        model="gpt-4o",
        target_domain="it-sicherheit.de",
        max_tokens=512,
        temperature=0.2,
    )
    result = adapter.probe(request)
    assert result.status is ProbeStatus.OK
    assert result.answer_text
    # web_search-Tool sollte Quellen liefern und die Suchen gezaehlt haben.
    assert result.citations
    assert (result.usage.server_search_requests or 0) >= 1
