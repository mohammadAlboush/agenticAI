"""Integration: kompletter Sprint-2-Flow offline (Messung + Lern-Loop), reproduzierbar.

Fuehrt den CrewAI-Flow ueber alle vier Schritte (sample -> report -> mine -> audit) mit
gemockten Ports aus und prueft Report, Templates, Findings und Determinismus (Seed 42).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
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
    assembly.storage.close()


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
