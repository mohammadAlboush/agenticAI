"""Phase-3-Gate: Settings-Parsing, Live-Flags, Reproduzierbarkeits-Fingerprint.

Die Tests isolieren sich ueber eine autouse-Fixture von der realen Umgebung
(loescht relevante Env-Variablen), damit sie maschinenunabhaengig deterministisch sind.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from geo_audit_loop.config import constants as c
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
    "INDEXNOW_KEY",
    "GEO_INDEXNOW_KEY_LOCATION",
    "GEO_NOTIFY_INDEX",
    "SERPER_API_KEY",
    "GEO_SERP_PROVIDER",
    "GEO_SERP_TOP_K",
    "GEO_SERP_QUERY_SET_VERSION",
    "GEO_ALLOW_REMOTE",
    "GEO_WP_BASE_URL",
    "WP_USERNAME",
    "WP_APP_PASSWORD",
    "GEO_MAX_REQUESTS_SERPER",
    "GEO_MAX_REQUESTS_GEMINI",
    "GEO_PUBLISHER",
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


def test_live_loop_defaults_are_safe() -> None:
    # Sicherheits-Defaults: kein SERP, kein IndexNow-Opt-in, kein Remote-Deploy.
    settings = Settings()
    assert settings.serp_provider == "off"
    assert settings.notify_index is False
    assert settings.allow_remote is False
    assert settings.indexnow_key is None
    assert settings.serper_api_key is None
    assert settings.wp_base_url is None
    assert settings.publisher == "mock"
    assert settings.serp_top_k == c.SERP_TOP_K
    assert settings.serp_query_set_version == c.DEFAULT_SERP_QUERY_SET_VERSION
    assert settings.max_requests_serper == c.DEFAULT_MAX_SERP_REQUESTS
    assert settings.max_requests_gemini is None


def test_live_loop_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEO_SERP_PROVIDER", "serper")
    monkeypatch.setenv("GEO_SERP_TOP_K", "5")
    monkeypatch.setenv("GEO_NOTIFY_INDEX", "true")
    monkeypatch.setenv("GEO_ALLOW_REMOTE", "true")
    monkeypatch.setenv("GEO_MAX_REQUESTS_GEMINI", "480")
    monkeypatch.setenv("GEO_PUBLISHER", "wordpress")
    settings = Settings()
    assert settings.serp_provider == "serper"
    assert settings.serp_top_k == 5
    assert settings.notify_index is True
    assert settings.allow_remote is True
    assert settings.max_requests_gemini == 480
    assert settings.publisher == "wordpress"


def test_empty_proxy_file_env_acts_like_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Phase-0-Befund: GEO_PROXY_FILE= (leer) wurde zu Path('.') -> PermissionError im
    # Live-Modus. Leerer String muss wie None wirken (kein Proxy-Pool).
    monkeypatch.setenv("GEO_PROXY_FILE", "")
    assert Settings().proxy_file is None
    monkeypatch.setenv("GEO_PROXY_FILE", "   ")
    assert Settings().proxy_file is None


def test_proxy_file_default_and_explicit_path(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().proxy_file == Path("Webshare 20 proxies (8).txt")
    monkeypatch.setenv("GEO_PROXY_FILE", "proxies.txt")
    assert Settings().proxy_file == Path("proxies.txt")


def test_fingerprint_sensitive_to_serp_provider_and_query_set() -> None:
    base = Settings()
    serp_on = Settings(serp_provider="mock")
    other_set = Settings(serp_query_set_version="v2")
    assert base.run_fingerprint() != serp_on.run_fingerprint()
    assert base.run_fingerprint() != other_set.run_fingerprint()
    assert serp_on.run_fingerprint() != other_set.run_fingerprint()


def test_fingerprint_insensitive_to_secrets_and_gates() -> None:
    # Keys/Gates sind keine Reproduzierbarkeits-Groessen: gleiche Messung, gleicher Hash.
    base = Settings()
    with_secrets = Settings(
        indexnow_key="a" * 16,
        serper_api_key="secret",
        wp_app_password="pw",
        notify_index=True,
        allow_remote=True,
    )
    assert base.run_fingerprint() == with_secrets.run_fingerprint()
