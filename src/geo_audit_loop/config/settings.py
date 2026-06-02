"""Settings & Secrets via pydantic-settings (.env). Keine Secrets im Code (Projektregeln §2/§6)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated

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

    # --- Proxies ---
    proxy_file: Path = Field(
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
        """Liefert den API-Key der Engine gemaess Registry (oder ``None``)."""
        env_name = ENGINE_REGISTRY[engine_id].api_key_env
        mapping = {
            "PERPLEXITY_API_KEY": self.perplexity_api_key,
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "OPENAI_API_KEY": self.openai_api_key,
            "GOOGLE_API_KEY": self.google_api_key,
        }
        return mapping.get(env_name)

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
            "models": {
                eid.value: cfg.model
                for eid, cfg in sorted(ENGINE_REGISTRY.items(), key=lambda kv: kv[0].value)
            },
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
