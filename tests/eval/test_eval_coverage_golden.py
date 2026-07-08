"""Eval-Harness: Golden-Regression der deterministischen Query-Intent-Coverage (Session 4).

Die Coverage ist eine reine, seed-stabile Domaenenfunktion (kein LLM/RNG). Dieser Test pinnt
ihre Offline-Ausgabe bei Seed 42 bit-genau: jede Aenderung an Intent-Tagging, Aggregation
oder Rundung wird als Regression sichtbar (tests/eval/README.md, Projektregeln §7). Anders
als die toleranzbasierten LLM-Evals ist hier exakte Gleichheit die Erwartung.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.orchestration.factory import assemble_run
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)
GOLDEN = Path(__file__).parent / "golden" / "coverage_it_sicherheit_seed42.json"


def test_coverage_matches_golden(tmp_path: Path) -> None:
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
        run_id="eval-coverage",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
    )
    assembly.pipeline.run()
    coverage = assembly.pipeline.coverage
    assembly.storage.close()

    assert coverage is not None
    dump = coverage.model_dump(mode="json", exclude={"run_id", "generated_at"})
    assert dump == golden["coverage"]  # bit-genau, deterministisch
