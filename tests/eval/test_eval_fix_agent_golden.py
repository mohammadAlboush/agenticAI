"""Eval (toleranzbasiert): Fix-Agent offline-deterministisch gegen ein Golden.

Prueft die Proposal-Anzahl in [min,max], die Verankerung jeder Proposal an einem echten
Finding + gueltigem Vokabular und die monotone Priorisierung nach der Citation-Pyramide
(tests/eval/README.md).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.fix import ChangeType
from geo_audit_loop.domain.geo import Lever, PyramidLevel, pyramid_rank
from geo_audit_loop.orchestration.factory import assemble_run
from geo_audit_loop.orchestration.sprint3_flow import Sprint3Pipeline
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)
GOLDEN = Path(__file__).parent / "golden" / "fix_agent_seed42.json"


def test_fix_agent_within_tolerance(tmp_path: Path) -> None:
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
        run_id="eval-fix",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
        fix=True,
    )
    assembly.pipeline.run()

    assert isinstance(assembly.pipeline, Sprint3Pipeline)
    plan = assembly.pipeline.fix_plan
    audit = assembly.pipeline.audit_report
    assembly.storage.close()
    assert plan is not None
    assert audit is not None

    assert golden["min_proposals"] <= len(plan.proposals) <= golden["max_proposals"]
    ranks = [pyramid_rank(p.pyramid_level) for p in plan.proposals]
    assert ranks == sorted(ranks)  # monoton nach Pyramide priorisiert
    finding_ids = {f.finding_id for f in audit.findings}
    for p in plan.proposals:
        assert isinstance(p.lever, Lever)
        assert isinstance(p.pyramid_level, PyramidLevel)
        assert isinstance(p.change_type, ChangeType)
        assert p.finding_id in finding_ids  # jede Proposal verweist auf ein echtes Finding
        assert p.proposed_content
        assert p.rationale
        assert 0.0 <= p.confidence <= 1.0
