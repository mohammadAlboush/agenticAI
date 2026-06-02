"""Phase-3-Gate: Settings-Parsing, Live-Flags, Reproduzierbarkeits-Fingerprint.

Die Tests isolieren sich ueber eine autouse-Fixture von der realen Umgebung
(loescht relevante Env-Variablen), damit sie maschinenunabhaengig deterministisch sind.
"""

from __future__ import annotations

import pytest

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.probe import EngineId

_ENV_VARS = (
    "PERPLEXITY_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEO_LIVE_ENGINES",
    "GEO_RUN_SEED",
    "GEO_N_PROXY_IPS",
    "GEO_TOP_N",
    "GEO_PROMPT_SET_VERSION",
    "GEO_MAX_PROBES",
    "GEO_MAX_USD",
    "GEO_MAX_TOKENS",
    "GEO_DB_PATH",
    "GEO_PROXY_FILE",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_parse_live_engines_from_comma_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEO_LIVE_ENGINES", "perplexity, claude")
    settings = Settings()
    assert settings.is_live(EngineId.PERPLEXITY)
    assert settings.is_live(EngineId.CLAUDE)
    assert not settings.is_live(EngineId.GEMINI)


def test_empty_live_engines_defaults_to_all_mock() -> None:
    settings = Settings()
    assert settings.live_engines == frozenset()
    assert not settings.is_live(EngineId.PERPLEXITY)


def test_api_key_lookup_uses_registry() -> None:
    settings = Settings(perplexity_api_key="pplx-secret")
    assert settings.api_key_for(EngineId.PERPLEXITY) == "pplx-secret"
    assert settings.api_key_for(EngineId.CHATGPT) is None


def test_fingerprint_is_deterministic_and_seed_sensitive() -> None:
    a = Settings(run_seed=42)
    b = Settings(run_seed=42)
    c = Settings(run_seed=7)
    assert a.run_fingerprint() == b.run_fingerprint()
    assert a.run_fingerprint() != c.run_fingerprint()


def test_budget_defaults_present() -> None:
    settings = Settings()
    assert settings.max_probes >= 1
    assert settings.max_usd >= 0.0
    assert settings.n_proxy_ips >= 1
