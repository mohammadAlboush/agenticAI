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

# --- ChatGPT (Live-Engine ueber die OpenAI-Responses-API mit web_search-Tool) ---
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

# --- Versioniertes Prompt-Set ---
DEFAULT_PROMPT_SET_VERSION: Final = "v1"

# --- Sprint 3: Fix-Agent / Deploy ---
FIX_AGENT_TASK: Final = "fix_agent"
PATCHES_SUBDIR: Final = "patches"  # Unterordner je Run fuer FilesystemPublisher-Artefakte

# --- Sprint 4: Effekt-Re-Probe + Gedaechtnis (geschlossener Lern-Loop) ---
EFFECT_ANALYST_TASK: Final = "effect_analyst"
# Memory-aware Fix-Prompt: unter --learn genutzt (v1 bleibt fuer reines --fix, Sprint 3).
FIX_AGENT_LEARN_VERSION: Final = "v2"
# Deterministische Confidence-Formel: n/(n+SHRINKAGE) daempft kleine Stichproben (kein RNG).
EFFECT_CONFIDENCE_SHRINKAGE: Final = 10
# Schwelle, ab der ein Delta als Verbesserung/Verschlechterung gilt (sonst UNCHANGED).
EFFECT_DIRECTION_EPSILON: Final = 0.01
# Memory-Retrieval: wie viele Hypothesen der naechste Fix-Run maximal einbezieht.
MEMORY_TOP_K: Final = 5
# Gewicht, mit dem eine erwiesene Hypothese die Patch-Confidence nudged (explizites Lern-Signal).
MEMORY_PRIOR_WEIGHT: Final = 0.15
# bge-m3 (CLAUDE.md §2): Standard-Embedding-Modell des optionalen Chroma-Memory-Adapters.
DEFAULT_EMBEDDING_MODEL: Final = "BAAI/bge-m3"

# --- Budget-Cap-Defaults (hart, Projektregeln §6) ---
DEFAULT_MAX_PROBES: Final = EXPECTED_PROBES_PER_RUN
DEFAULT_MAX_USD: Final = 2.0
DEFAULT_MAX_TOKENS_BUDGET: Final = 2_000_000

# --- Live-Loop: SERP-Sichtbarkeit (Serper.dev, Google-Top-10 vs. AI-Zitate) ---
SERPER_ENDPOINT: Final = "https://google.serper.dev/search"
SERP_TOP_K: Final = 10  # Google-Top-10 als Vergleichsmenge
N_SERP_QUERIES: Final = 12  # 1:1 auf die 12 Probe-Prompts gemappt
DEFAULT_SERP_QUERY_SET_VERSION: Final = "v1"
SERP_GL: Final = "de"  # Geolokation der SERP-Abfrage (Land)
SERP_HL: Final = "de"  # Interface-Sprache der SERP-Abfrage
# Pro-Provider-Request-Quote: 12 Queries x 2 Phasen = 24 Requests/Run reichen.
DEFAULT_MAX_SERP_REQUESTS: Final = 24

# --- Live-Loop: IndexNow (URLs nach echtem Deploy bei Bing/Yandex/Naver/Seznam einreichen) ---
INDEXNOW_ENDPOINT: Final = "https://api.indexnow.org/indexnow"
INDEXNOW_TIMEOUT_S: Final = 10.0
# Key-Regeln laut IndexNow-Protokoll: 8-128 Zeichen (a-z, A-Z, 0-9, Bindestrich).
INDEXNOW_KEY_MIN_LEN: Final = 8
INDEXNOW_KEY_MAX_LEN: Final = 128
INDEXNOW_MAX_URLS_PER_BATCH: Final = 10_000  # Protokoll-Limit pro POST

# --- Live-Loop: WordPress-Deploy (Backup-vor-Write, Projektregeln §6) ---
BACKUPS_SUBDIR: Final = "backups"  # Unterordner je Run fuer Pre-Write-Backups
