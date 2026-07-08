"""Integration: der wissenschaftlich tragende Nachweis — das System LERNT (nicht nur speichert).

Zeigt zwei Wege, wie ein gespeicherter Effekt den NAECHSTEN Fix-Run messbar veraendert:
(1) zwei aufeinanderfolgende Laeufe auf derselben DB (Lauf 2 nutzt das Gedaechtnis von Lauf 1),
(2) eine gezielt vorab gesetzte Hypothese hebt die Confidence genau des passenden Patches.
Beides ist offline deterministisch (Mock-Gedaechtnis + Mock-Reasoning + Code-Reweighting).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.effect import EffectDirection, EffectHypothesis
from geo_audit_loop.domain.fix import ChangeType
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.memory.mock import MockMemoryAdapter
from geo_audit_loop.orchestration.factory import RunAssembly, assemble_run
from geo_audit_loop.orchestration.sprint4_flow import Sprint4Pipeline
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _assembly(db_path: Path, *, run_id: str, learn: bool) -> RunAssembly:
    settings = Settings(db_path=db_path, max_probes=1000, n_proxy_ips=5, top_n=5, run_seed=42)
    version, prompts = load_probe_set("v1")
    return assemble_run(
        settings,
        domain="it-sicherheit.de",
        offline=True,
        run_id=run_id,
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
        fix=not learn,
        learn=learn,
    )


def _confidences(assembly: RunAssembly) -> dict[str, float]:
    pipeline = assembly.pipeline
    assert isinstance(pipeline, Sprint4Pipeline)
    plan = pipeline.fix_plan
    assert plan is not None
    return {p.patch_id: p.confidence for p in plan.proposals}


def test_second_run_learns_from_first(tmp_path: Path) -> None:
    db = tmp_path / "geo.db"
    # Lauf 1: leeres Gedaechtnis -> Plan wie Sprint 3, Hypothesen werden gespeichert.
    first = _assembly(db, run_id="r1", learn=True)
    first.pipeline.run()
    conf_first = _confidences(first)
    first.storage.close()

    # Lauf 2: dasselbe Gedaechtnis (jetzt gefuellt) -> abgerufene Effekte veraendern den Plan.
    second = _assembly(db, run_id="r2", learn=True)
    second.pipeline.run()
    pipeline = second.pipeline
    assert isinstance(pipeline, Sprint4Pipeline)
    conf_second = _confidences(second)
    retrieved = pipeline.retrieved_memory
    second.storage.close()

    assert retrieved  # Lauf 2 hat aus dem Gedaechtnis gelesen
    assert conf_second != conf_first  # ... und der Plan hat sich messbar geaendert (Lernen)


def _hypothesis() -> EffectHypothesis:
    # Erwiesen starker positiver Effekt fuer (fact_density, insert_block) -> px-f1-insert_block.
    return EffectHypothesis(
        hypothesis_id="eh-seed-px-f1-insert_block",
        run_id="seed",
        target_domain="it-sicherheit.de",
        target_url="https://www.it-sicherheit.de/firewall-grundlagen",
        patch_id="px-f1-insert_block",
        finding_id="f1",
        lever=Lever.FACT_DENSITY,
        pyramid_level=PyramidLevel.SUBSTANCE,
        change_type=ChangeType.INSERT_BLOCK,
        before_citation_rate=0.02,
        after_citation_rate=0.92,
        before_n=240,
        after_n=240,
        delta=0.9,
        direction=EffectDirection.IMPROVED,
        confidence=1.0,
        suspected_cause="seed",
        observed_at=FIXED,
    )


def test_seeded_hypothesis_boosts_matching_patch(tmp_path: Path) -> None:
    # Baseline ohne Gedaechtnis.
    base_db = tmp_path / "base.db"
    base = _assembly(base_db, run_id="base", learn=True)
    base.pipeline.run()
    base_conf = _confidences(base)
    base.storage.close()

    # Frische DB mit gezielt vorab gesetzter Hypothese.
    seeded_db = tmp_path / "seeded.db"
    memory = MockMemoryAdapter(seeded_db)
    memory.store(_hypothesis())
    memory.close()

    seeded = _assembly(seeded_db, run_id="seeded", learn=True)
    seeded.pipeline.run()
    seeded_conf = _confidences(seeded)
    seeded.storage.close()

    # Genau der passende Patch steigt in der Confidence; andere bleiben unveraendert.
    assert seeded_conf["px-f1-insert_block"] > base_conf["px-f1-insert_block"]
    assert seeded_conf["px-f2-add_schema"] == base_conf["px-f2-add_schema"]
