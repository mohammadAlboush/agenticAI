"""Eval (toleranzbasiert): Pattern-Miner offline-deterministisch gegen ein Golden.

Nicht-deterministische Agenten docken an dieselbe Golden-Struktur an, pruefen aber
TOLERANZBASIERT (Anzahl in [min,max], Hebel-/Pyramide-Verankerung) statt exakter
Stringgleichheit (tests/eval/README.md). Offline laeuft der deterministische Mock.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.orchestration.factory import assemble_run
from geo_audit_loop.orchestration.sprint2_flow import Sprint2Pipeline
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)
GOLDEN = Path(__file__).parent / "golden" / "pattern_miner_seed42.json"


def test_pattern_miner_within_tolerance(tmp_path: Path) -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    settings = Settings(
        db_path=tmp_path / "geo.db",
        max_probes=1000,
        n_proxy_ips=5,
        top_n=5,
        run_seed=golden["seed"],
    )
    version, prompts = load_probe_set(golden["prompt_set_version"])
    assembly = assemble_run(
        settings,
        domain=golden["domain"],
        offline=True,
        run_id="eval-pm",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
        explain=True,
    )
    assembly.pipeline.run()
    assembly.storage.close()

    assert isinstance(assembly.pipeline, Sprint2Pipeline)
    report = assembly.pipeline.pattern_report
    assert report is not None
    assert golden["min_templates"] <= len(report.templates) <= golden["max_templates"]
    for template in report.templates:
        assert all(isinstance(lever, Lever) for lever in template.levers)
        assert isinstance(template.pyramid_level, PyramidLevel)
        assert 0.0 <= template.confidence <= 1.0
        assert template.evidence_urls
