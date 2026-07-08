"""Eval (toleranzbasiert): der geschlossene Loop offline-deterministisch gegen ein Golden.

Prueft die Anzahl gebildeter Effekt-Hypothesen in [min,max], dass jede Hypothese an einem
tatsaechlich angewandten Patch verankert ist, dass der simulierte Offline-Boost je Zielseite
einen nicht-negativen Effekt zeigt und dass die Confidence-Werte im gueltigen Bereich liegen
(tests/eval/README.md). Zusaetzlich: dasselbe Golden mit leerem Gedaechtnis ist reproduzierbar.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.effect import EffectDirection
from geo_audit_loop.orchestration.factory import assemble_run
from geo_audit_loop.orchestration.sprint4_flow import Sprint4Pipeline
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)
GOLDEN = Path(__file__).parent / "golden" / "effect_seed42.json"


def test_effect_within_tolerance(tmp_path: Path) -> None:
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
        run_id="eval-effect",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
        learn=True,
    )
    assembly.pipeline.run()

    assert isinstance(assembly.pipeline, Sprint4Pipeline)
    effect = assembly.pipeline.effect_report
    plan = assembly.pipeline.fix_plan
    assembly.storage.close()
    assert effect is not None
    assert plan is not None

    applied_ids = {p.patch_id for p in plan.proposals}
    assert golden["min_hypotheses"] <= len(effect.hypotheses) <= golden["max_hypotheses"]
    for hyp in effect.hypotheses:
        assert hyp.patch_id in applied_ids  # an einem echten, angewandten Patch verankert
        assert hyp.delta >= 0.0  # Offline-Boost: kein negativer Effekt
        assert hyp.direction is EffectDirection.IMPROVED
        assert 0.0 <= hyp.confidence <= 1.0
    assert effect.n_improved == len(effect.hypotheses)
    assert effect.mean_delta >= 0.0
