"""Eval (toleranzbasiert): der Wettbewerbs-Share-of-Voice offline-deterministisch gegen ein Golden.

Prueft die Anzahl zitierter Domains in [min,max], dass genau EINE Zeile die Zieldomain ist,
dass die Rangfolge nach Haeufigkeit faellt (totaler Ordnungsschluessel) und dass alle Shares im
gueltigen Bereich liegen. Reine Domaenen-Mathematik -> deterministisch (kein LLM); ein Golden-
Unit-Test genuegt (kein Agenten-Eval-Slot noetig). Details: tests/eval/README.md.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.orchestration.factory import assemble_run
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)
GOLDEN = Path(__file__).parent / "golden" / "share_of_voice_seed42.json"


def test_share_of_voice_within_tolerance(tmp_path: Path) -> None:
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
        run_id="eval-sov",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
    )
    assembly.pipeline.run()
    report = assembly.storage.load_sov_report("eval-sov")
    assembly.storage.close()

    assert report is not None
    assert golden["min_hosts"] <= len(report.shares) <= golden["max_hosts"]
    # Genau eine Zeile ist die Zieldomain.
    assert sum(1 for s in report.shares if s.is_target) == 1
    target = next(s for s in report.shares if s.is_target)
    assert target.domain == golden["domain"]
    assert report.target_rank is not None
    assert report.target_share == target.citation_rate
    # Rangfolge faellt (totaler Ordnungsschluessel), Shares gueltig.
    counts = [s.citation_count for s in report.shares]
    assert counts == sorted(counts, reverse=True)
    assert all(0.0 <= s.citation_rate <= 1.0 for s in report.shares)
    # Wettbewerber-Seiten sind Nicht-Ziel-Seiten.
    assert all(p.domain != golden["domain"] for p in report.top_competitor_pages)
