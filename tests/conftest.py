"""Pytest-Setup: Telemetrie aus + hermetische Umgebung (keine echte .env im Test).

(1) CrewAI/OTEL-Telemetrie wird abgeschaltet, bevor crewai importiert wird.
(2) Tests muessen reproduzierbar sein, UNABHAENGIG von einer lokalen ``.env``:
    - pydantic-settings liest die Datei nicht (``env_file=None``);
    - CrewAI ruft beim Import jedoch ``load_dotenv()`` auf und schiebt die ``.env``
      nach ``os.environ`` — wegen ``validation_alias`` ueberstimmt das sonst sogar
      explizite ``Settings(...)``-Argumente. Die autouse-Fixture loescht die
      projekteigenen Variablen daher vor jedem Test wieder aus ``os.environ``.
"""

import os

import pytest

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from geo_audit_loop.config.settings import Settings

Settings.model_config["env_file"] = None

_PROJECT_ENV = (
    "PERPLEXITY_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "SAIA_API_KEY",
    "GEO_LIVE_ENGINES",
    "GEO_REASONING_PROVIDER",
    "GEO_SAIA_BASE_URL",
    "GEO_SAIA_MODEL",
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
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Entfernt projekteigene Env-Variablen (auch die von CrewAIs load_dotenv geladenen)."""
    for name in _PROJECT_ENV:
        monkeypatch.delenv(name, raising=False)
