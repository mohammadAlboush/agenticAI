"""Unit: Loader fuer versionierte Agenten-Prompts und das SERP-Query-Set."""

from __future__ import annotations

import pytest

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain.errors import ConfigError
from geo_audit_loop.prompts.loader import load_probe_set, load_prompt, load_serp_query_set


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


def test_load_serp_query_set_returns_12_keyword_queries() -> None:
    version, queries = load_serp_query_set("v1")
    assert version == "v1"
    assert len(queries) == c.N_SERP_QUERIES
    assert len({q.query_id for q in queries}) == c.N_SERP_QUERIES  # eindeutige IDs
    for query in queries:
        assert not query.text.endswith("?")  # Keyword-Queries, keine Fragesaetze


def test_serp_queries_map_one_to_one_onto_probe_prompts() -> None:
    # Topic-Join: jede Query gehoert zu genau einem Probe-Prompt derselben Version.
    _, prompts = load_probe_set("v1")
    _, queries = load_serp_query_set("v1")
    assert {q.prompt_id for q in queries} == {p.prompt_id for p in prompts}
    assert len({q.prompt_id for q in queries}) == len(queries)  # 1:1, kein Prompt doppelt


def test_load_serp_query_set_missing_version_raises() -> None:
    with pytest.raises(ConfigError):
        load_serp_query_set("v999")
