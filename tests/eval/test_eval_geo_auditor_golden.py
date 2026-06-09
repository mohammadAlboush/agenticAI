"""Eval (toleranzbasiert): GEO-Auditor offline-deterministisch gegen ein Golden.

Prueft die Findings-Anzahl in [min,max], Hebel-/Pyramide-/Severity-Verankerung mit Beleg
und die monotone Priorisierung nach der Citation-Pyramide (tests/eval/README.md).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.audit import Severity
from geo_audit_loop.domain.geo import Lever, PyramidLevel, pyramid_rank
from geo_audit_loop.orchestration.factory import assemble_run
from geo_audit_loop.orchestration.sprint2_flow import Sprint2Pipeline
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)
GOLDEN = Path(__file__).parent / "golden" / "geo_auditor_seed42.json"


def test_geo_auditor_within_tolerance(tmp_path: Path) -> None:
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
        run_id="eval-ga",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
        explain=True,
    )
    assembly.pipeline.run()
    assembly.storage.close()

    assert isinstance(assembly.pipeline, Sprint2Pipeline)
    report = assembly.pipeline.audit_report
    assert report is not None
    assert golden["min_findings"] <= len(report.findings) <= golden["max_findings"]
    ranks = [pyramid_rank(f.pyramid_level) for f in report.findings]
    assert ranks == sorted(ranks)  # monoton nach Pyramide priorisiert
    for finding in report.findings:
        assert isinstance(finding.lever, Lever)
        assert isinstance(finding.pyramid_level, PyramidLevel)
        assert isinstance(finding.severity, Severity)
        assert finding.evidence
        assert finding.recommendation
