"""Unit: deterministisches SQLite-Gedaechtnis (MockMemoryAdapter) — Kern des Lern-Loops."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from geo_audit_loop.domain.effect import EffectDirection, EffectHypothesis
from geo_audit_loop.domain.fix import ChangeType
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.domain.memory import MemoryQuery
from geo_audit_loop.memory.mock import MockMemoryAdapter

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _hyp(
    *,
    hid: str,
    domain: str = "it-sicherheit.de",
    lever: Lever = Lever.ANSWER_BLOCKS,
    change_type: ChangeType = ChangeType.INSERT_BLOCK,
    delta: float = 0.5,
    confidence: float = 0.8,
    observed_at: datetime = FIXED,
) -> EffectHypothesis:
    return EffectHypothesis(
        hypothesis_id=hid,
        run_id="r0",
        target_domain=domain,
        target_url=f"https://www.{domain}/page",
        patch_id=f"px-{hid}",
        finding_id="f1",
        lever=lever,
        pyramid_level=PyramidLevel.EXTRACTABILITY,
        change_type=change_type,
        before_citation_rate=0.0,
        after_citation_rate=round(delta, 6),
        before_n=240,
        after_n=240,
        delta=round(delta, 6),
        direction=EffectDirection.IMPROVED if delta > 0 else EffectDirection.REGRESSED,
        confidence=confidence,
        suspected_cause="x",
        observed_at=observed_at,
    )


def _memory(tmp_path: Path) -> MockMemoryAdapter:
    return MockMemoryAdapter(tmp_path / "geo.db")


def test_store_and_retrieve_roundtrip(tmp_path: Path) -> None:
    mem = _memory(tmp_path)
    hyp = _hyp(hid="h1")
    mem.store(hyp)
    got = mem.retrieve(MemoryQuery(target_domain="it-sicherheit.de"))
    assert got == [hyp]


def test_domain_isolation(tmp_path: Path) -> None:
    mem = _memory(tmp_path)
    mem.store(_hyp(hid="h1", domain="it-sicherheit.de"))
    # Abruf fuer eine ANDERE Domain darf nichts zurueckgeben (Lern-Leck verhindert).
    assert mem.retrieve(MemoryQuery(target_domain="example.com")) == []


def test_lever_filter(tmp_path: Path) -> None:
    mem = _memory(tmp_path)
    mem.store(_hyp(hid="h1", lever=Lever.ANSWER_BLOCKS))
    mem.store(_hyp(hid="h2", lever=Lever.MACHINE_READABLE))
    got = mem.retrieve(MemoryQuery(target_domain="it-sicherheit.de", lever=Lever.ANSWER_BLOCKS))
    assert [h.hypothesis_id for h in got] == ["h1"]


def test_deterministic_order_by_confidence_then_delta(tmp_path: Path) -> None:
    mem = _memory(tmp_path)
    mem.store(_hyp(hid="low", confidence=0.4, delta=0.9))
    mem.store(_hyp(hid="high", confidence=0.9, delta=0.2))
    mem.store(_hyp(hid="mid", confidence=0.6, delta=0.6))
    got = mem.retrieve(MemoryQuery(target_domain="it-sicherheit.de"))
    assert [h.hypothesis_id for h in got] == ["high", "mid", "low"]


def test_top_k_limits_results(tmp_path: Path) -> None:
    mem = _memory(tmp_path)
    for i in range(6):
        mem.store(_hyp(hid=f"h{i}", confidence=0.5 + i / 100))
    got = mem.retrieve(MemoryQuery(target_domain="it-sicherheit.de", top_k=2))
    assert len(got) == 2
    assert got[0].confidence > got[1].confidence  # hoechste zuerst


def test_store_is_idempotent(tmp_path: Path) -> None:
    mem = _memory(tmp_path)
    mem.store(_hyp(hid="h1", confidence=0.5))
    mem.store(_hyp(hid="h1", confidence=0.9))  # gleiche id -> Upsert, kein Duplikat
    got = mem.retrieve(MemoryQuery(target_domain="it-sicherheit.de"))
    assert len(got) == 1
    assert got[0].confidence == 0.9


def test_retrieve_is_deterministic_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "geo.db"
    mem = MockMemoryAdapter(db)
    for i in range(4):
        mem.store(_hyp(hid=f"h{i}", confidence=0.7, delta=0.5))  # gleiche Rangwerte -> id-Tiebreak
    order1 = [h.hypothesis_id for h in mem.retrieve(MemoryQuery(target_domain="it-sicherheit.de"))]
    mem.close()
    # frische Instanz auf derselben DB liefert exakt dieselbe Reihenfolge (id ASC als Tiebreak)
    mem2 = MockMemoryAdapter(db)
    order2 = [h.hypothesis_id for h in mem2.retrieve(MemoryQuery(target_domain="it-sicherheit.de"))]
    assert order1 == order2 == ["h0", "h1", "h2", "h3"]
