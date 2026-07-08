"""Integration: kompletter Sprint-2-Flow offline (Messung + Lern-Loop), reproduzierbar.

Fuehrt den CrewAI-Flow ueber alle vier Schritte (sample -> report -> mine -> audit) mit
gemockten Ports aus und prueft Report, Templates, Findings und Determinismus (Seed 42).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.run import RunStatus
from geo_audit_loop.orchestration.factory import assemble_run
from geo_audit_loop.orchestration.sprint2_flow import Sprint2Pipeline
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def test_sprint2_flow_offline_produces_patterns_and_findings(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "geo.db", max_probes=1000, n_proxy_ips=5, top_n=5, run_seed=42
    )
    version, prompts = load_probe_set("v1")
    assembly = assemble_run(
        settings,
        domain="it-sicherheit.de",
        offline=True,
        run_id="it-s2",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
        explain=True,
    )

    assembly.flow.kickoff()

    assert isinstance(assembly.pipeline, Sprint2Pipeline)
    assert assembly.pipeline.report is not None
    assert assembly.pipeline.report.n_probes == 4 * len(prompts) * settings.n_proxy_ips
    patterns = assembly.pipeline.pattern_report
    audit = assembly.pipeline.audit_report
    assert patterns is not None
    assert patterns.templates
    assert audit is not None
    assert audit.findings

    # Sprint 2.1: Lern-Artefakte persistiert + Run-Kosten enthalten das Reasoning
    assert assembly.storage.load_pattern_report("it-s2") is not None
    assert assembly.storage.load_audit_report("it-s2") is not None
    run = assembly.storage.load_run("it-s2")
    snapshot_tokens = assembly.cost_tracker.snapshot().total_tokens
    assembly.storage.close()
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    assert run.total_tokens == snapshot_tokens  # Finalize nach Audit => Reasoning inklusive
    assert run.total_tokens > 0

    con = sqlite3.connect(str(settings.db_path))
    n_log = con.execute(
        "SELECT COUNT(*) FROM reasoning_log WHERE run_id = ?", ("it-s2",)
    ).fetchone()[0]
    con.close()
    assert n_log >= 2  # je ein Reasoning-Aufruf fuer Pattern-Miner und GEO-Auditor


def test_entity_extractor_enriches_graph_with_same_as(tmp_path: Path) -> None:
    """Session 8 (LLM): der Entity-Extractor fuellt brand_same_as + regeneriert den JSON-LD.

    Der Extractor laeuft in jedem S2-Lauf (die Marke ist immer vorhanden); nach dem Flow traegt
    der Entity-Graph valide sameAs-URLs und der empfohlene JSON-LD-Block enthaelt sie.
    """
    settings = Settings(
        db_path=tmp_path / "geo.db", max_probes=1000, n_proxy_ips=5, top_n=5, run_seed=42
    )
    version, prompts = load_probe_set("v1")
    assembly = assemble_run(
        settings,
        domain="it-sicherheit.de",
        offline=True,
        run_id="it-ee",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
        explain=True,
    )
    assembly.flow.kickoff()

    assert isinstance(assembly.pipeline, Sprint2Pipeline)
    graph = assembly.pipeline.entity_graph
    stored = assembly.storage.load_entity_graph("it-ee")
    assembly.storage.close()
    assert graph is not None
    assert graph.brand_same_as  # sameAs-URLs gefunden
    assert all(url.startswith(("http://", "https://")) for url in graph.brand_same_as)
    assert "sameAs" in graph.recommended_jsonld  # in den JSON-LD-Fix eingebaut
    assert stored is not None
    assert stored.brand_same_as == graph.brand_same_as  # re-persistiert


def test_sprint2_is_reproducible(tmp_path: Path) -> None:
    version, prompts = load_probe_set("v1")

    def _run(db: Path) -> tuple[int, int, str]:
        settings = Settings(db_path=db, max_probes=1000, n_proxy_ips=5, top_n=5, run_seed=42)
        assembly = assemble_run(
            settings,
            domain="it-sicherheit.de",
            offline=True,
            run_id="it-s2",
            now=FIXED,
            prompts=prompts,
            prompt_version=version,
            explain=True,
        )
        assembly.pipeline.run()
        assert isinstance(assembly.pipeline, Sprint2Pipeline)
        patterns = assembly.pipeline.pattern_report
        audit = assembly.pipeline.audit_report
        assembly.storage.close()
        assert patterns is not None
        assert audit is not None
        assert audit.findings
        return len(patterns.templates), len(audit.findings), audit.findings[0].target_url

    assert _run(tmp_path / "a.db") == _run(tmp_path / "b.db")
