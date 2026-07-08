"""Unit: Effekt-Analyst — Baseline vs. Re-Probe -> Hypothese -> Gedaechtnis + Persistenz."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
from geo_audit_loop.agents.effect_analyst import EffectAnalystService
from geo_audit_loop.domain.effect import EffectDirection
from geo_audit_loop.domain.fix import ChangeType, FixProposal
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.domain.memory import MemoryQuery
from geo_audit_loop.domain.probe import (
    Citation,
    EngineId,
    ProbePhase,
    ProbeResult,
    ProbeStatus,
)
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.memory.mock import MockMemoryAdapter

FIXED = datetime(2026, 1, 1, 12, 0, 0)
_URL = "https://www.it-sicherheit.de/firewall-grundlagen"


def _ctx() -> RunContext:
    return RunContext(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        started_at=FIXED,
        seed=42,
        prompt_set_version="v1",
        config_hash="hash",
    )


def _probe(idx: int, *, phase: ProbePhase, cites: bool) -> ProbeResult:
    citations = (Citation(url=_URL, engine=EngineId.GEMINI, rank=1),) if cites else ()
    return ProbeResult(
        run_id="run-1",
        engine_id=EngineId.GEMINI,
        model="mock",
        prompt_id=f"p{idx}",
        prompt_version="v1",
        proxy_label="proxy-0",
        citations=citations,
        status=ProbeStatus.OK,
        probed_at=FIXED,
        phase=phase,
    )


def _proposal() -> FixProposal:
    return FixProposal(
        patch_id="px-f1-insert_block",
        finding_id="f1",
        target_url=_URL,
        lever=Lever.FACT_DENSITY,
        pyramid_level=PyramidLevel.SUBSTANCE,
        change_type=ChangeType.INSERT_BLOCK,
        proposed_content="Ein Faktenblock.",
        rationale="Template t2.",
        confidence=0.78,
    )


def test_effect_analyst_forms_stores_and_persists(tmp_path: Path) -> None:
    db = tmp_path / "geo.db"
    storage = SqliteStorage(db)
    storage.initialize()
    memory = MockMemoryAdapter(db)
    # Baseline: URL nie zitiert. Re-Probe: URL immer zitiert (simulierter Fix-Effekt).
    for i in range(10):
        storage.save_probe(_probe(i, phase=ProbePhase.BASELINE, cites=False))
        storage.save_probe(_probe(i, phase=ProbePhase.REPROBE, cites=True))

    analyst = EffectAnalystService(memory=memory, storage=storage, clock=lambda: FIXED)
    report = analyst.run(_ctx(), [_proposal()], "v2")

    assert len(report.hypotheses) == 1
    hyp = report.hypotheses[0]
    assert hyp.before_citation_rate == 0.0
    assert hyp.after_citation_rate == 1.0
    assert hyp.delta == 1.0
    assert hyp.direction is EffectDirection.IMPROVED
    assert report.n_improved == 1

    # persistiert im StoragePort ...
    assert storage.load_effect_report("run-1") == report
    # ... und im Gedaechtnis (MemoryPort) fuer den naechsten Lauf abrufbar.
    recalled = memory.retrieve(MemoryQuery(target_domain="it-sicherheit.de"))
    assert [h.hypothesis_id for h in recalled] == [hyp.hypothesis_id]


def test_effect_analyst_no_applied_patches(tmp_path: Path) -> None:
    db = tmp_path / "geo.db"
    storage = SqliteStorage(db)
    storage.initialize()
    memory = MockMemoryAdapter(db)
    analyst = EffectAnalystService(memory=memory, storage=storage, clock=lambda: FIXED)
    report = analyst.run(_ctx(), [], "v2")
    assert report.hypotheses == ()
    assert report.n_improved == 0
    assert memory.retrieve(MemoryQuery(target_domain="it-sicherheit.de")) == []
