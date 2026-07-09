"""Opt-in Live-Smoke-Test gegen die echte Serper.dev-API (1 Query vom Free-Kontingent).

Standardmaessig uebersprungen. Bewusst ausfuehren mit:
    GEO_RUN_LIVE_TESTS=1 SERPER_API_KEY=... uv run pytest -m live
"""

from __future__ import annotations

import os

import pytest

from geo_audit_loop.adapters.serp.serper import SerperSerpAdapter
from geo_audit_loop.domain.probe import ProbeStatus
from geo_audit_loop.domain.serp import SerpProvider, SerpQuery, SerpRequest

pytestmark = pytest.mark.live

# Beim Import gelesen (die hermetische Env-Fixture scrubbt SERPER_API_KEY vor jedem Test).
_API_KEY = os.getenv("SERPER_API_KEY", "")
_OPT_IN = bool(os.getenv("GEO_RUN_LIVE_TESTS")) and bool(_API_KEY)


@pytest.mark.skipif(not _OPT_IN, reason="Live-Tests nur mit GEO_RUN_LIVE_TESTS=1 + API-Key")
def test_live_serper_smoke() -> None:
    adapter = SerperSerpAdapter(api_key=_API_KEY)
    request = SerpRequest(
        run_id="live-smoke",
        query=SerpQuery(
            query_id="q01",
            text="NIS2 Richtlinie Anforderungen Unternehmen",
            prompt_id="p01",
        ),
        top_k=10,
    )
    result = adapter.search(request)
    assert result.status is ProbeStatus.OK
    assert result.provider is SerpProvider.SERPER
    assert result.entries
    assert all(entry.position >= 1 for entry in result.entries)
    assert all(entry.url.startswith("http") for entry in result.entries)
