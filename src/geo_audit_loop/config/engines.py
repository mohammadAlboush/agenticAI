"""Engine-Registry: Modell, Suchmodus und API-Key-Quelle je Engine.

Der Kern hardcodet nie ein Modell; Adapter und Sampler beziehen den opaken
Vendor-String aus dieser Registry. So ergaenzt man eine fuenfte Engine, ohne den
Kern anzufassen (Projektregeln §3.1).
"""

from __future__ import annotations

from pydantic import Field

from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.probe import EngineId, SearchMode


class EngineConfig(FrozenModel):
    """Statische Konfiguration einer Engine."""

    engine_id: EngineId
    model: str = Field(min_length=1)
    api_key_env: str = Field(min_length=1)
    search_mode: SearchMode | None = None


ENGINE_REGISTRY: dict[EngineId, EngineConfig] = {
    EngineId.PERPLEXITY: EngineConfig(
        engine_id=EngineId.PERPLEXITY,
        model="sonar-pro",
        api_key_env="PERPLEXITY_API_KEY",
        search_mode=SearchMode.WEB,
    ),
    EngineId.CLAUDE: EngineConfig(
        engine_id=EngineId.CLAUDE,
        model="claude-sonnet-4-6",
        api_key_env="ANTHROPIC_API_KEY",
    ),
    EngineId.CHATGPT: EngineConfig(
        engine_id=EngineId.CHATGPT,
        # gpt-4o: Responses-API-faehig inkl. web_search-Tool; der Modellname muss zum
        # Preis-Eintrag in config/pricing.py passen (usd_per_search-Kostenwarnung dort).
        model="gpt-4o",
        api_key_env="OPENAI_API_KEY",
    ),
    EngineId.GEMINI: EngineConfig(
        engine_id=EngineId.GEMINI,
        # 2.5-flash: einziges Modell mit Grounding im Free Tier (gemini-2.0-flash
        # wurde am 2026-06-01 abgeschaltet; Gemini-3-Grounding ist Free-Tier-gesperrt).
        model="gemini-2.5-flash",
        api_key_env="GOOGLE_API_KEY",
    ),
}
