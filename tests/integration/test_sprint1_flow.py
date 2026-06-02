"""Phase-8-Gate: kompletter Sprint-1-Flow offline (alle Ports gemockt, kein Netz).

Fuehrt den CrewAI-Flow ueber die volle 240er-Matrix (4 Engines x 12 Prompts x 5 IPs)
aus und prueft Report, Persistenz und Run-Lifecycle - die reproduzierbare DEMO-Form.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.run import RunStatus
from geo_audit_loop.orchestration.factory import assemble_run
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def test_full_offline_pipeline_produces_report(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "geo.db",
        max_probes=1000,
        n_proxy_ips=5,
        top_n=5,
        run_seed=42,
    )
    version, prompts = load_probe_set("v1")
    assembly = assemble_run(
        settings,
        domain="it-sicherheit.de",
        offline=True,
        run_id="it-run",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
    )

    assembly.flow.kickoff()
    report = assembly.pipeline.report

    assert report is not None
    assert report.n_pages > 0
    assert report.n_probes == 4 * len(prompts) * settings.n_proxy_ips  # 4 Engines
    assert len(report.engine_aggregates) == 4 * len(prompts)
    assert report.top and report.flop
    assert report.top[0].citation_count >= report.flop[0].citation_count

    run = assembly.storage.load_run("it-run")
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    assert run.total_probes == report.n_probes
    assert assembly.cost_tracker.snapshot().probes == report.n_probes
    assembly.storage.close()


def test_pipeline_is_reproducible(tmp_path: Path) -> None:
    version, prompts = load_probe_set("v1")

    def _run(db: Path) -> tuple[int, str]:
        settings = Settings(db_path=db, max_probes=1000, n_proxy_ips=5, top_n=5, run_seed=42)
        assembly = assemble_run(
            settings,
            domain="it-sicherheit.de",
            offline=True,
            run_id="it-run",
            now=FIXED,
            prompts=prompts,
            prompt_version=version,
        )
        report = assembly.pipeline.run()  # framework-freier Komplettlauf
        assembly.storage.close()
        return report.top[0].citation_count, report.top[0].url

    assert _run(tmp_path / "a.db") == _run(tmp_path / "b.db")
