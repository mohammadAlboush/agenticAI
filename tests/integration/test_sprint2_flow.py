"""Integration: kompletter Sprint-2-Flow offline (Messung + Lern-Loop), reproduzierbar.

Fuehrt den CrewAI-Flow ueber alle vier Schritte (sample -> report -> mine -> audit) mit
gemockten Ports aus und prueft Report, Templates, Findings und Determinismus (Seed 42).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.coverage import CoverageReport, IntentCoverage
from geo_audit_loop.domain.probe import QueryIntent
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


def test_query_generator_enriches_coverage_when_blind_spots_exist(tmp_path: Path) -> None:
    """Session 4 (LLM): bei schwachen Intents fuellt der Query-Generator suggested_queries.

    Das Offline-Sample hat keine Blind Spots (alle Intents abgedeckt) -> hier wird eine
    schwache Coverage injiziert, um die Anreicherungs-Verdrahtung in ``mine_patterns`` aktiv
    zu pruefen (Property + Re-Persistenz).
    """
    settings = Settings(
        db_path=tmp_path / "geo.db", max_probes=1000, n_proxy_ips=5, top_n=5, run_seed=42
    )
    version, prompts = load_probe_set("v1")
    assembly = assemble_run(
        settings,
        domain="it-sicherheit.de",
        offline=True,
        run_id="it-qg",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
        explain=True,
    )
    pipeline = assembly.pipeline
    assert isinstance(pipeline, Sprint2Pipeline)
    pipeline.sample()
    pipeline.crawl_and_report()

    # Blind Spot erzwingen: Coverage mit einem schwachen Intent injizieren.
    weak = (QueryIntent.TROUBLESHOOTING,)
    weak_coverage = CoverageReport(
        run_id="it-qg",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        n_probes=48,
        overall_citation_rate=0.2,
        intents=(
            IntentCoverage(
                intent=QueryIntent.TROUBLESHOOTING,
                n_prompts=1,
                n_covered=0,
                coverage_rate=0.0,
                mean_citation_rate=0.0,
            ),
        ),
        weakest_intents=weak,
    )
    pipeline._base._coverage = weak_coverage
    assembly.storage.save_coverage_report(weak_coverage)

    pipeline.mine_patterns()

    enriched = pipeline.coverage
    stored = assembly.storage.load_coverage_report("it-qg")
    assembly.storage.close()
    assert enriched is not None
    assert enriched.suggested_queries  # Luecken-Fragen erzeugt
    assert all(q.intent is QueryIntent.TROUBLESHOOTING for q in enriched.suggested_queries)
    assert stored is not None
    assert stored.suggested_queries == enriched.suggested_queries  # re-persistiert


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
