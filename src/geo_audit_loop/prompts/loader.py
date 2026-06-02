"""Lader fuer versionierte Probe-Sets (Projektregeln §3.3: Prompts als Artefakte)."""

from __future__ import annotations

import tomllib
from importlib.resources import files

from geo_audit_loop.domain.errors import ConfigError
from geo_audit_loop.domain.probe import ProbePrompt


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
