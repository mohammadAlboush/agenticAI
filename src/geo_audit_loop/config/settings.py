"""Settings & Secrets via pydantic-settings (.env). Keine Secrets im Code (Projektregeln §2/§6)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from geo_audit_loop.config import constants as c
from geo_audit_loop.config.engines import ENGINE_REGISTRY
from geo_audit_loop.domain.probe import EngineId


class Settings(BaseSettings):
    """Zentrale Laufzeit-Konfiguration; liest ``.env`` und Umgebungsvariablen."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- Secrets (unpraefixiert, damit die SDKs sie ebenfalls finden) ---
    perplexity_api_key: str | None = Field(default=None, validation_alias="PERPLEXITY_API_KEY")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    saia_api_key: str | None = Field(default=None, validation_alias="SAIA_API_KEY")

    # --- SAIA / KISSKI (Hochschul-LLM-Dienst, OpenAI-kompatibel; kostenloses Reasoning) ---
    saia_base_url: str = Field(
        default="https://chat-ai.academiccloud.de/v1", validation_alias="GEO_SAIA_BASE_URL"
    )
    saia_model: str = Field(default="openai-gpt-oss-120b", validation_alias="GEO_SAIA_MODEL")
    # Welcher Adapter den ReasoningPort bedient (Pattern-Miner/GEO-Auditor):
    # mock (Default, deterministisch) | saia (Hochschule, kostenlos) | claude (Anthropic, paid).
    reasoning_provider: Literal["mock", "saia", "claude"] = Field(
        default="mock", validation_alias="GEO_REASONING_PROVIDER"
    )

    # --- Proxies ---
    # None = kein Proxy-Pool. Ein leerer String in GEO_PROXY_FILE wirkt wie None
    # (sonst wuerde Path("") zum Arbeitsverzeichnis '.' und der Live-Modus scheitert
    # mit PermissionError beim Oeffnen eines Verzeichnisses).
    proxy_file: Path | None = Field(
        default=Path("Webshare 20 proxies (8).txt"), validation_alias="GEO_PROXY_FILE"
    )

    # --- Run-Steuerung ---
    # NoDecode: Roh-String aus der Env nicht als JSON dekodieren, sondern unten als
    # Komma-Liste parsen (sonst scheitert pydantic-settings an "perplexity,claude").
    live_engines: Annotated[frozenset[EngineId], NoDecode] = Field(
        default_factory=frozenset, validation_alias="GEO_LIVE_ENGINES"
    )
    run_seed: int = Field(default=42, validation_alias="GEO_RUN_SEED")
    n_proxy_ips: int = Field(default=c.N_PROXY_IPS, ge=1, validation_alias="GEO_N_PROXY_IPS")
    top_n: int = Field(default=c.TOP_N, ge=1, validation_alias="GEO_TOP_N")
    prompt_set_version: str = Field(
        default=c.DEFAULT_PROMPT_SET_VERSION, validation_alias="GEO_PROMPT_SET_VERSION"
    )

    # --- Budget-Cap (hart, Projektregeln §6) ---
    max_probes: int = Field(default=c.DEFAULT_MAX_PROBES, ge=1, validation_alias="GEO_MAX_PROBES")
    max_usd: float = Field(default=c.DEFAULT_MAX_USD, ge=0.0, validation_alias="GEO_MAX_USD")
    max_tokens: int = Field(
        default=c.DEFAULT_MAX_TOKENS_BUDGET, ge=0, validation_alias="GEO_MAX_TOKENS"
    )

    # --- Pfade ---
    db_path: Path = Field(default=Path("runs/geo_audit.db"), validation_alias="GEO_DB_PATH")
    runs_dir: Path = Field(default=Path("runs"), validation_alias="GEO_RUNS_DIR")

    # --- Sprint 3: Deploy-Ziel (sicher; github bewusst NICHT waehlbar) ---
    # mock (Default, Dry-Run, kein Write) | filesystem (Patch-Artefakte nach runs/<id>/patches/)
    # | wordpress (echte Site — nur hinter dem allow_remote-Gate, sonst ConfigError).
    publisher: Literal["mock", "filesystem", "wordpress"] = Field(
        default="mock", validation_alias="GEO_PUBLISHER"
    )

    # --- Sprint 4: Gedaechtnis-Backend (Lern-Loop) ---
    # mock (Default, deterministisch, SQLite) | chroma (bge-m3, opt-in Extra 'memory', nicht det.).
    memory_provider: Literal["mock", "chroma"] = Field(
        default="mock", validation_alias="GEO_MEMORY_PROVIDER"
    )
    chroma_path: Path = Field(default=Path("runs/chroma"), validation_alias="GEO_CHROMA_PATH")
    embedding_model: str = Field(
        default=c.DEFAULT_EMBEDDING_MODEL, validation_alias="GEO_EMBEDDING_MODEL"
    )

    # --- Live-Loop: IndexNow (Einreichen geaenderter URLs nach echtem Deploy) ---
    indexnow_key: str | None = Field(default=None, validation_alias="INDEXNOW_KEY")
    # Abweichender Standort der Key-Datei (Default: https://<host>/<key>.txt).
    indexnow_key_location: str | None = Field(
        default=None, validation_alias="GEO_INDEXNOW_KEY_LOCATION"
    )
    # Opt-in: nur wenn True (UND non-dry-run-Deploy) wird ueberhaupt eingereicht.
    notify_index: bool = Field(default=False, validation_alias="GEO_NOTIFY_INDEX")

    # --- Live-Loop: SERP-Sichtbarkeit (Google-Top-10 vs. AI-Zitate) ---
    serper_api_key: str | None = Field(default=None, validation_alias="SERPER_API_KEY")
    # off (Default, exakter No-Op — Offline-Fingerprint bleibt unveraendert)
    # | mock (seed-deterministisch) | serper (Live, google.serper.dev).
    serp_provider: Literal["off", "mock", "serper"] = Field(
        default="off", validation_alias="GEO_SERP_PROVIDER"
    )
    serp_top_k: int = Field(default=c.SERP_TOP_K, ge=1, validation_alias="GEO_SERP_TOP_K")
    serp_query_set_version: str = Field(
        default=c.DEFAULT_SERP_QUERY_SET_VERSION, validation_alias="GEO_SERP_QUERY_SET_VERSION"
    )

    # --- Live-Loop: Remote-Deploy (WordPress; Doppel-Gate mit CLI --allow-remote) ---
    allow_remote: bool = Field(default=False, validation_alias="GEO_ALLOW_REMOTE")
    wp_base_url: str | None = Field(default=None, validation_alias="GEO_WP_BASE_URL")
    wp_username: str | None = Field(default=None, validation_alias="WP_USERNAME")
    wp_app_password: str | None = Field(default=None, validation_alias="WP_APP_PASSWORD")

    # --- Live-Loop: Pro-Provider-Request-Quoten (zusaetzlich zu den globalen Caps) ---
    max_requests_serper: int = Field(
        default=c.DEFAULT_MAX_SERP_REQUESTS, ge=0, validation_alias="GEO_MAX_REQUESTS_SERPER"
    )
    # None = keine Provider-Quote (nur globale Caps); fuer das Gemini-Free-Tier setzbar.
    max_requests_gemini: int | None = Field(
        default=None, ge=0, validation_alias="GEO_MAX_REQUESTS_GEMINI"
    )

    @field_validator("proxy_file", mode="before")
    @classmethod
    def _empty_proxy_file_is_none(cls, value: object) -> object:
        """``GEO_PROXY_FILE=`` (leer) bedeutet: kein Proxy-Pool — wie ``None``."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("live_engines", mode="before")
    @classmethod
    def _parse_live_engines(cls, value: object) -> object:
        """Erlaubt Komma-Listen aus der Umgebung (z.B. ``perplexity,claude``)."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def is_live(self, engine_id: EngineId) -> bool:
        """True, wenn diese Engine real abgefragt werden soll (sonst Mock)."""
        return engine_id in self.live_engines

    def api_key_for(self, engine_id: EngineId) -> str | None:
        """Liefert den (ersten) API-Key der Engine gemaess Registry (oder ``None``)."""
        env_name = ENGINE_REGISTRY[engine_id].api_key_env
        mapping = {
            "PERPLEXITY_API_KEY": self.perplexity_api_key,
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "OPENAI_API_KEY": self.openai_api_key,
            "GOOGLE_API_KEY": self.google_api_key,
        }
        raw = mapping.get(env_name)
        return raw.split(",")[0].strip() if raw else None

    def api_keys_for(self, engine_id: EngineId) -> list[str]:
        """Alle konfigurierten Keys der Engine (Komma-Liste = mehrere Projekte/Kontingente)."""
        env_name = ENGINE_REGISTRY[engine_id].api_key_env
        if env_name == "GOOGLE_API_KEY" and self.google_api_key:
            return [k.strip() for k in self.google_api_key.split(",") if k.strip()]
        single = self.api_key_for(engine_id)
        return [single] if single else []

    def run_fingerprint(self) -> str:
        """Stabiler Hash der reproduzierbarkeits-relevanten Konfiguration (Projektregeln §7)."""
        payload = {
            "seed": self.run_seed,
            "n_proxy_ips": self.n_proxy_ips,
            "max_probes": self.max_probes,
            "max_usd": self.max_usd,
            "max_tokens": self.max_tokens,
            "prompt_set_version": self.prompt_set_version,
            "live_engines": sorted(e.value for e in self.live_engines),
            # Sprint 4: Mock (deterministisch) vs. Chroma (semantisch) sind unterschiedliche
            # Reproduzierbarkeits-Klassen; chroma_path/embedding_model bleiben irrelevant.
            "memory_provider": self.memory_provider,
            # Live-Loop: off/mock/serper sind unterschiedliche Reproduzierbarkeits-Klassen
            # (analog memory_provider); das Query-Set bestimmt die Vergleichsmenge.
            "serp_provider": self.serp_provider,
            "serp_query_set_version": self.serp_query_set_version,
            # top_k bestimmt die SERP-Vergleichsmenge und damit die Overlap-Werte.
            "serp_top_k": self.serp_top_k,
            "models": {
                eid.value: cfg.model
                for eid, cfg in sorted(ENGINE_REGISTRY.items(), key=lambda kv: kv[0].value)
            },
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
