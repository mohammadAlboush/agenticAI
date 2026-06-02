"""Eval-Harness (Phase 9): Golden-Regression der deterministischen S1-Pipeline.

S1-Agenten (Sampler/Crawler) sind deterministisch -> dieser Golden-Test pinnt die
Top-Rangfolge bei festem Seed. Aenderungen an Mock-/Aggregations-/Scoring-Logik werden
hier als Regression sichtbar. Nicht-deterministische Agenten (S2) docken toleranzbasiert
an derselben Struktur an.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.orchestration.factory import assemble_run
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)
GOLDEN = Path(__file__).parent / "golden" / "topflop_it_sicherheit_seed42.json"


def test_topflop_matches_golden(tmp_path: Path) -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    settings = Settings(
        db_path=tmp_path / "geo.db",
        max_probes=1000,
        n_proxy_ips=5,
        top_n=10,
        run_seed=golden["seed"],
    )
    version, prompts = load_probe_set(golden["prompt_set_version"])
    assembly = assemble_run(
        settings,
        domain=golden["domain"],
        offline=True,
        run_id="eval-run",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
    )
    report = assembly.pipeline.run()
    assembly.storage.close()

    assert [entry.url for entry in report.top] == golden["top_urls"]
    counts = [entry.citation_count for entry in report.top]
    assert counts == sorted(counts, reverse=True)  # monoton fallend
