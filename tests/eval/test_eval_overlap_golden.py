"""Eval-Harness: Golden-Regression des SERP-Overlap (Live-Loop, Mock-Provider).

``compute_overlap`` und der Mock-SERP-Adapter sind deterministisch -> dieser Golden-Test
pinnt ``mean_jaccard`` und die Per-Query-Kennzahlen bei Seed 42 EXAKT (keine Toleranz).
Aenderungen an Mock-SERP, Mock-Engine-Zitaten, URL-Normalisierung oder der
Overlap-Mathematik werden hier als Regression sichtbar. Golden erzeugt durch einen
echten Offline-Lauf (GEO_SERP_PROVIDER=mock, hermetische Settings wie in conftest).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.orchestration.factory import assemble_run
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)
GOLDEN = Path(__file__).parent / "golden" / "overlap_it_sicherheit_seed42.json"


def test_overlap_matches_golden(tmp_path: Path) -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    settings = Settings(
        db_path=tmp_path / "geo.db",
        max_probes=1000,
        n_proxy_ips=5,
        top_n=5,
        run_seed=golden["seed"],
        serp_provider="mock",
        serp_query_set_version=golden["serp_query_set_version"],
    )
    version, prompts = load_probe_set(golden["prompt_set_version"])
    assembly = assemble_run(
        settings,
        domain=golden["domain"],
        offline=True,
        run_id="eval-overlap",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
    )
    assembly.pipeline.run()
    overlap = assembly.pipeline.overlap_report
    assembly.storage.close()

    assert overlap is not None
    assert overlap.provider.value == golden["provider"]
    assert overlap.query_set_version == golden["serp_query_set_version"]
    assert overlap.n_queries == golden["n_queries"]
    # Exakte Pins (Rundung auf 6 Stellen ist Teil des Contracts -> bit-stabil).
    assert overlap.mean_jaccard == golden["mean_jaccard"]
    assert overlap.mean_ai_in_serp_share == golden["mean_ai_in_serp_share"]
    assert len(overlap.stats) == len(golden["stats"])
    for stat, expected in zip(overlap.stats, golden["stats"], strict=True):
        assert stat.query_id == expected["query_id"]
        assert stat.prompt_id == expected["prompt_id"]
        assert stat.jaccard == expected["jaccard"]
        assert stat.ai_in_serp_share == expected["ai_in_serp_share"]
        assert stat.domain_jaccard == expected["domain_jaccard"]
        assert stat.target_serp_rank == expected["target_serp_rank"]
        assert stat.target_ai_citation_rate == expected["target_ai_citation_rate"]
        assert stat.n_serp_urls == expected["n_serp_urls"]
        assert stat.n_ai_urls == expected["n_ai_urls"]
