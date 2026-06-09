"""Unit: Markdown-Prompt-Loader fuer die versionierten Agenten-Prompts."""

from __future__ import annotations

import pytest

from geo_audit_loop.domain.errors import ConfigError
from geo_audit_loop.prompts.loader import load_prompt


def test_load_prompt_returns_version_and_text() -> None:
    version, text = load_prompt("pattern_miner")
    assert version == "v1"
    assert "Pattern-Miner" in text


def test_load_geo_auditor_prompt() -> None:
    _, text = load_prompt("geo_auditor")
    assert "GEO-Auditor" in text


def test_load_prompt_missing_raises() -> None:
    with pytest.raises(ConfigError):
        load_prompt("does_not_exist")
