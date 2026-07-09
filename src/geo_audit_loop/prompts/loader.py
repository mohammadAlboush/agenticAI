"""Lader fuer versionierte Probe-Sets (Projektregeln §3.3: Prompts als Artefakte)."""

from __future__ import annotations

import tomllib
from importlib.resources import files

from geo_audit_loop.domain.errors import ConfigError
from geo_audit_loop.domain.probe import ProbePrompt
from geo_audit_loop.domain.serp import SerpQuery


def load_probe_set(version: str = "v1") -> tuple[str, list[ProbePrompt]]:
    """Laedt ``probe_set.<version>.toml`` und liefert (Version, Prompts).

    Wirft ``ConfigError``, wenn die Datei fehlt oder leer ist.
    """
    resource = files("geo_audit_loop.prompts").joinpath(f"probe_set.{version}.toml")
    if not resource.is_file():
        raise ConfigError(f"Probe-Set nicht gefunden: probe_set.{version}.toml")
    data = tomllib.loads(resource.read_text(encoding="utf-8"))
    raw_prompts = data.get("prompts") or []
    prompts = [ProbePrompt(prompt_id=item["id"], text=item["text"]) for item in raw_prompts]
    if not prompts:
        raise ConfigError(f"Probe-Set probe_set.{version}.toml enthaelt keine Prompts")
    return str(data.get("version", version)), prompts


def load_serp_query_set(version: str = "v1") -> tuple[str, list[SerpQuery]]:
    """Laedt ``serp_queries.<version>.toml`` und liefert (Version, Keyword-Queries).

    Jede Query traegt ihre ``prompt_id`` als Topic-Join zum gleichnamigen
    Probe-Prompt (Overlap-Vergleich). Wirft ``ConfigError``, wenn die Datei
    fehlt oder keine Queries enthaelt.
    """
    resource = files("geo_audit_loop.prompts").joinpath(f"serp_queries.{version}.toml")
    if not resource.is_file():
        raise ConfigError(f"SERP-Query-Set nicht gefunden: serp_queries.{version}.toml")
    data = tomllib.loads(resource.read_text(encoding="utf-8"))
    raw_queries = data.get("queries") or []
    queries = [
        SerpQuery(query_id=item["id"], text=item["text"], prompt_id=item["prompt_id"])
        for item in raw_queries
    ]
    if not queries:
        raise ConfigError(f"SERP-Query-Set serp_queries.{version}.toml enthaelt keine Queries")
    return str(data.get("version", version)), queries


def load_prompt(name: str, version: str = "v1") -> tuple[str, str]:
    """Laedt ein versioniertes Markdown-Prompt ``<name>.<version>.md`` und liefert (Version, Text).

    Fuer die LLM-Agenten (Pattern-Miner, GEO-Auditor): der Text ist der System-Prompt;
    der Agent haengt die konkreten Eingabedaten als User-Nachricht an. Die genutzte
    Version wird pro Run protokolliert (Reproduzierbarkeit, Projektregeln §3.3).
    Wirft ``ConfigError``, wenn die Datei fehlt oder leer ist.
    """
    resource = files("geo_audit_loop.prompts").joinpath(f"{name}.{version}.md")
    if not resource.is_file():
        raise ConfigError(f"Prompt nicht gefunden: {name}.{version}.md")
    text = resource.read_text(encoding="utf-8").strip()
    if not text:
        raise ConfigError(f"Prompt {name}.{version}.md ist leer")
    return version, text
