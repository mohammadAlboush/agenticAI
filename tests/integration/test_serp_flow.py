"""Integration: SERP-Overlap im Sprint-1-Flow (Live-Loop, Mock-Provider offline).

Prueft: (1) mit ``GEO_SERP_PROVIDER=mock`` wird der Overlap-Report berechnet und
persistiert, alle 12 Queries laufen als Provider-Requests; (2) der Checkpoint macht
einen Resume-Lauf request-frei (0 neue SERP-Calls); (3) mit ``off`` (Default) bleibt
der Report byte-identisch zum bisherigen Verhalten — der Fingerprint ohne Overlap
entspricht exakt dem eines Laufs ohne SERP-Provider (kein ``"overlap": null``-Key).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.fingerprint import report_fingerprint
from geo_audit_loop.domain.serp import SerpProvider
from geo_audit_loop.orchestration.factory import RunAssembly, assemble_run
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)
N_QUERIES = 12  # serp_queries.v1.toml (q01..q12)


def _assembly(
    tmp_path: Path, *, provider: Literal["off", "mock", "serper"], run_id: str = "serp-run"
) -> RunAssembly:
    settings = Settings(
        db_path=tmp_path / "geo.db",
        max_probes=1000,
        n_proxy_ips=5,
        top_n=5,
        run_seed=42,
        serp_provider=provider,
    )
    version, prompts = load_probe_set("v1")
    return assemble_run(
        settings,
        domain="it-sicherheit.de",
        offline=True,
        run_id=run_id,
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
    )


def test_mock_serp_computes_and_persists_overlap(tmp_path: Path) -> None:
    assembly = _assembly(tmp_path, provider="mock")
    assembly.pipeline.run()

    overlap = assembly.pipeline.overlap_report
    assert overlap is not None
    assert overlap.provider is SerpProvider.MOCK
    assert overlap.n_queries == N_QUERIES
    assert overlap.query_set_version == "v1"
    assert len(overlap.stats) == N_QUERIES
    # Persistenz: Report + alle SERP-Ergebnisse liegen in der DB.
    assert assembly.storage.load_overlap_report("serp-run") == overlap
    serp_results = assembly.storage.load_serp_results("serp-run", SerpProvider.MOCK)
    assert len(serp_results) == N_QUERIES
    # Quota-Buchhaltung: jede Query hat genau einen SERP-Provider-Request verbucht
    # (die Engine-Probes zaehlen separat unter ihren eigenen Provider-Schluesseln).
    snapshot = assembly.cost_tracker.snapshot()
    assembly.storage.close()
    assert snapshot.requests_by_provider["mock"] == N_QUERIES


def test_mock_serp_checkpoint_resume_makes_no_new_requests(tmp_path: Path) -> None:
    first = _assembly(tmp_path, provider="mock")
    first.pipeline.run()
    overlap_first = first.pipeline.overlap_report
    first.storage.close()
    assert overlap_first is not None

    # Resume mit derselben DB + run_id: alle (run_id, provider, query_id)-Zellen
    # sind bereits persistiert -> der Checkpoint macht den Lauf SERP-request-frei.
    resumed = _assembly(tmp_path, provider="mock", run_id="serp-run")
    resumed.pipeline.run()
    overlap_resumed = resumed.pipeline.overlap_report
    snapshot = resumed.cost_tracker.snapshot()
    resumed.storage.close()
    assert snapshot.requests_by_provider.get("mock", 0) == 0
    # Der Overlap wird aus den persistierten Ergebnissen identisch rekonstruiert.
    assert overlap_resumed is not None
    assert overlap_resumed.stats == overlap_first.stats
    assert overlap_resumed.mean_jaccard == overlap_first.mean_jaccard
    assert overlap_resumed.mean_ai_in_serp_share == overlap_first.mean_ai_in_serp_share


def test_serp_off_is_exact_noop_and_fingerprint_is_unchanged(tmp_path: Path) -> None:
    (tmp_path / "off").mkdir()
    (tmp_path / "mock").mkdir()
    off = _assembly(tmp_path / "off", provider="off")
    off.pipeline.run()
    report_off = off.pipeline.report
    assert off.pipeline.overlap_report is None
    assert off.storage.load_overlap_report("serp-run") is None
    assert off.storage.load_serp_results("serp-run") == []
    # Kein SERP-Provider => kein einziger SERP-Request (Engine-Probes zaehlen separat).
    requests = off.cost_tracker.snapshot().requests_by_provider
    assert "mock" not in requests
    assert "serper" not in requests
    off.storage.close()
    assert report_off is not None

    # Mock-SERP beeinflusst die Probe-Matrix nicht: der Report-Fingerprint OHNE Overlap
    # ist byte-identisch zum off-Lauf; erst der Overlap-Report aendert den Hash.
    mock = _assembly(tmp_path / "mock", provider="mock")
    mock.pipeline.run()
    report_mock = mock.pipeline.report
    overlap_mock = mock.pipeline.overlap_report
    mock.storage.close()
    assert report_mock is not None
    assert overlap_mock is not None
    assert report_fingerprint(report_off) == report_fingerprint(report_mock)
    assert report_fingerprint(report_mock, overlap=overlap_mock) != report_fingerprint(report_off)
