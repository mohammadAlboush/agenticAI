"""Zentrale Konstanten (keine Magic Numbers/Strings im Code, Projektregeln §4)."""

from __future__ import annotations

from typing import Final

# --- Probe-Matrix (Pitch: 5 IPs x 4 Engines x 12 Prompts = 240 Probes/Run) ---
N_PROXY_IPS: Final = 5
N_ENGINES: Final = 4
N_PROMPTS: Final = 12
EXPECTED_PROBES_PER_RUN: Final = N_PROXY_IPS * N_ENGINES * N_PROMPTS  # 240

# --- Engine-Abfrage-Defaults ---
DEFAULT_MAX_TOKENS: Final = 1024
DEFAULT_TEMPERATURE: Final = 0.2

# --- Reasoning (Pattern-Miner/GEO-Auditor/Fix-Agent): temperature 0 => deterministischer ---
REASONING_TEMPERATURE: Final = 0.0
# Reasoning braucht mehr Output-Budget als Engine-Probes: der Fix-Agent erzeugt je Patch
# laengeren Inhalt (Textblock/JSON-LD). 1024 reicht echten LLMs nicht -> JSON wird abgeschnitten.
REASONING_MAX_TOKENS: Final = 4096
# Inhalts-Auszug pro Seite (Groessenkappung fuer Persistenz + LLM-Kontext)
CONTENT_EXCERPT_WORDS: Final = 300

# --- Perplexity (Live-Engine seit Sprint 1) ---
PERPLEXITY_ENDPOINT: Final = "https://api.perplexity.ai/chat/completions"

# --- Claude (Anthropic Messages API mit Web-Search-Server-Tool; Live-Engine, S1) ---
ANTHROPIC_ENDPOINT: Final = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION: Final = "2023-06-01"
# Basis-Variante des Web-Search-Tools: modell-agnostisch (auch Haiku/Sonnet), liefert Quellen-URLs.
ANTHROPIC_WEB_SEARCH_TOOL_TYPE: Final = "web_search_20250305"

# --- ChatGPT (OpenAI Responses API mit web_search-Tool; Live-Engine, S1) ---
OPENAI_RESPONSES_ENDPOINT: Final = "https://api.openai.com/v1/responses"

# --- Gemini (Live-Engine mit Google-Search-Grounding; Free Tier 500 Anfragen/Tag) ---
GEMINI_ENDPOINT_TEMPLATE: Final = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
# Eigen-Drosselung fuer das Free-Tier-Rate-Limit (~10 Anfragen/Minute, Stand 2026-06).
GEMINI_MIN_INTERVAL_S: Final = 6.5

# --- Crawler ---
DEFAULT_USER_AGENT: Final = "geo-audit-loop/0.1 (+research; kontakt@alboush-elektro.de)"
DEFAULT_MAX_PAGES: Final = 200
DEFAULT_DOWNLOAD_DELAY_S: Final = 1.0
DEFAULT_CONCURRENT_PER_DOMAIN: Final = 2

# --- Retry / Backoff (externe Aufrufe, Projektregeln §6) ---
RETRY_MAX_ATTEMPTS: Final = 3
RETRY_BASE_DELAY_S: Final = 1.0
RETRY_MAX_DELAY_S: Final = 30.0

# --- Report ---
TOP_N: Final = 10

# --- Competitive Intelligence (Share of Voice) ---
# Wie viele Wettbewerber-Domains bzw. -Seiten der SoV-Report maximal auflistet.
SOV_TOP_DOMAINS: Final = 10
SOV_TOP_COMPETITOR_PAGES: Final = 10
# --- Query-Intent-Coverage (Session 4) ---
# Coverage-Rate (Anteil zitierter Prompts je Intent), unter der ein Intent als Blind Spot gilt.
COVERAGE_WEAK_THRESHOLD: Final = 0.5
# Query-Generator (Session 4, LLM): Task-Label + wie viele Luecken-Fragen je schwachem Intent.
QUERY_GENERATOR_TASK: Final = "query_generator"
QUERY_GENERATOR_MAX_PER_INTENT: Final = 3

# --- Entitaeten-Klarheit / Knowledge-Graph (Session 8) ---
# Gewichtete Rubrik der Entitaeten-Klarheit je Seite (Summe der Gewichte = 1.0).
ENTITY_CLARITY_WEIGHTS: Final[dict[str, float]] = {
    "organization": 0.35,  # Organization/WebSite in JSON-LD deklariert (staerkstes Signal)
    "opengraph": 0.20,  # OpenGraph gibt Entitaets-Name/-Typ/-URL
    "author": 0.20,  # Autor als Person-Entitaet (E-E-A-T)
    "canonical": 0.15,  # stabile Kanonical-URL als @id-Anker
    "lang": 0.10,  # Sprach-Attribut (Entitaets-Disambiguierung)
}
# schema.org-Typen, die die Domain als Organisations-Entitaet ausweisen.
ORGANIZATION_SCHEMA_TYPES: Final = frozenset(
    {"Organization", "Corporation", "LocalBusiness", "NewsMediaOrganization", "WebSite"}
)
# Klarheits-Score, unter dem eine Seite als Entitaeten-Luecke gilt.
ENTITY_CLARITY_WEAK_THRESHOLD: Final = 0.5
# Entity-Extractor (Session 8, LLM): Task-Label + Obergrenze der sameAs-Autoritaets-URLs.
ENTITY_EXTRACTOR_TASK: Final = "entity_extractor"
ENTITY_EXTRACTOR_MAX_SAME_AS: Final = 5
# --- Continuous Monitoring / Trend (Session 7) ---
# Delta der Gesamt-Zitationsrate (letzter vs. vorheriger Lauf), unter dem ein Intent-uebergreifender
# Rueckgang als Drift-Alert gilt (deterministischer Schwellenwert; KI-Signifikanz folgt mit #1).
TREND_DRIFT_THRESHOLD: Final = 0.10
# Betrag, ab dem ein Delta ueberhaupt als Richtung (besser/schlechter) statt STABIL gilt.
TREND_DIRECTION_EPSILON: Final = 0.01

# --- Versioniertes Prompt-Set ---
DEFAULT_PROMPT_SET_VERSION: Final = "v1"

# --- Sprint 3: Fix-Agent / Deploy ---
FIX_AGENT_TASK: Final = "fix_agent"
PATCHES_SUBDIR: Final = "patches"  # Unterordner je Run fuer FilesystemPublisher-Artefakte

# --- Sprint 4: Effekt-Re-Probe + Gedaechtnis (geschlossener Lern-Loop) ---
EFFECT_ANALYST_TASK: Final = "effect_analyst"
# Memory-aware Fix-Prompt: unter --learn genutzt (v1 bleibt fuer reines --fix, Sprint 3).
FIX_AGENT_LEARN_VERSION: Final = "v2"
# Schwelle, ab der ein Delta als Verbesserung/Verschlechterung gilt (sonst UNCHANGED).
# Wirkt als Effektstaerke-Untergrenze ZUSAETZLICH zur statistischen Signifikanz (s.u.).
EFFECT_DIRECTION_EPSILON: Final = 0.01
# Memory-Retrieval: wie viele Hypothesen der naechste Fix-Run maximal einbezieht.
MEMORY_TOP_K: Final = 5
# Gewicht, mit dem eine erwiesene Hypothese die Patch-Confidence nudged (explizites Lern-Signal).
MEMORY_PRIOR_WEIGHT: Final = 0.15

# --- Sprint 5: Statistisch fundierte Effekt-Messung (Wilson/Newcombe) ---
# Zweiseitiges 95%-Normalquantil (z) fuer Wilson-Score- und Newcombe-Difference-KI.
# Ein gemessener Vorher/Nachher-Lift gilt nur dann als Effekt, wenn sein 95%-KI die Null
# ausschliesst -> der Lern-Loop lernt nicht mehr aus statistischem Rauschen (Projektregeln §1/§7).
EFFECT_CI_Z: Final = 1.959963984540054
# Recency-Decay im Memory-Prior: je (Hebel, Aenderungsart)-Gruppe zaehlt jede aeltere
# Hypothese geometrisch weniger (0.5 = halbes Gewicht je Rang). Deterministisch ueber den Satz.
MEMORY_RECENCY_DECAY: Final = 0.5
# bge-m3 (CLAUDE.md §2): Standard-Embedding-Modell des optionalen Chroma-Memory-Adapters.
DEFAULT_EMBEDDING_MODEL: Final = "BAAI/bge-m3"

# --- Budget-Cap-Defaults (hart, Projektregeln §6) ---
DEFAULT_MAX_PROBES: Final = EXPECTED_PROBES_PER_RUN
DEFAULT_MAX_USD: Final = 2.0
DEFAULT_MAX_TOKENS_BUDGET: Final = 2_000_000
