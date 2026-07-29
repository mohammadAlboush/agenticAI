"""Phase-4-Gate: SQLite-Persistenz inkl. Idempotenz/Checkpoint-Resume."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from geo_audit_loop.adapters.sample_data import build_sample_inventory
from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
from geo_audit_loop.domain.effect import (
    EffectDirection,
    EffectHypothesis,
    EffectReport,
    derive_hypothesis_id,
)
from geo_audit_loop.domain.findings import TopFlopEntry, TopFlopReport
from geo_audit_loop.domain.fix import (
    ApprovalDecision,
    ChangeType,
    DeployResult,
    DeployStatus,
    FixPlan,
    FixProposal,
)
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.domain.indexing import (
    EndpointResult,
    IndexingEndpoint,
    IndexSubmissionResult,
    IndexSubmissionStatus,
)
from geo_audit_loop.domain.overlap import OverlapReport, OverlapStat
from geo_audit_loop.domain.probe import (
    Citation,
    EngineId,
    ProbePhase,
    ProbeResult,
    ProbeStatus,
    ProbeUsage,
)
from geo_audit_loop.domain.run import RunRecord, RunStatus
from geo_audit_loop.domain.serp import RankEntry, SerpProvider, SerpResult

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _storage(tmp_path: Path) -> SqliteStorage:
    storage = SqliteStorage(tmp_path / "geo.db")
    storage.initialize()
    return storage


def _run(status: RunStatus = RunStatus.RUNNING) -> RunRecord:
    return RunRecord(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        status=status,
        started_at=FIXED,
        seed=42,
        prompt_set_version="v1",
        config_hash="abc",
    )


def _probe(
    prompt_id: str = "p1",
    proxy_label: str = "proxy-0",
    phase: ProbePhase = ProbePhase.BASELINE,
) -> ProbeResult:
    return ProbeResult(
        run_id="run-1",
        engine_id=EngineId.PERPLEXITY,
        model="m",
        prompt_id=prompt_id,
        prompt_version="v1",
        proxy_label=proxy_label,
        citations=(
            Citation(url="https://it-sicherheit.de/nis2", engine=EngineId.PERPLEXITY, rank=1),
        ),
        target_cited=True,
        target_rank=1,
        usage=ProbeUsage(total_tokens=10),
        status=ProbeStatus.OK,
        probed_at=FIXED,
        phase=phase,
    )


def test_run_roundtrip(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    run = _run()
    storage.save_run(run)
    assert storage.load_run("run-1") == run
    assert storage.load_run("unknown") is None


def test_list_runs_newest_first(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    assert storage.list_runs() == []
    storage.save_run(_run())
    newer = _run().model_copy(
        update={"run_id": "run-2", "started_at": datetime(2026, 1, 2, 12, 0, 0)}
    )
    storage.save_run(newer)
    runs = storage.list_runs()
    assert [r.run_id for r in runs] == ["run-2", "run-1"]


def test_list_runs_handles_mixed_timezone_awareness(tmp_path: Path) -> None:
    # Reale DBs koennen naive UND tz-bewusste started_at mischen -> Sort darf nicht crashen.
    storage = _storage(tmp_path)
    naive = _run().model_copy(update={"run_id": "naive", "started_at": datetime(2026, 1, 1, 9, 0)})
    aware = _run().model_copy(
        update={"run_id": "aware", "started_at": datetime(2026, 1, 1, 10, 0, tzinfo=UTC)}
    )
    storage.save_run(naive)
    storage.save_run(aware)
    runs = storage.list_runs()  # darf nicht werfen
    assert [r.run_id for r in runs] == ["aware", "naive"]  # 10:00 UTC vor 09:00 UTC


def test_delete_run_removes_all_artifacts(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.save_run(_run())
    storage.save_probe(_probe())
    storage.save_pages("run-1", build_sample_inventory())
    storage.delete_run("run-1")
    assert storage.load_run("run-1") is None
    assert storage.load_probes("run-1") == []
    assert storage.load_pages("run-1") == []
    storage.delete_run("unbekannt")  # idempotent, kein Fehler


def test_update_run(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.save_run(_run())
    storage.update_run(_run().model_copy(update={"status": RunStatus.COMPLETED, "total_probes": 5}))
    loaded = storage.load_run("run-1")
    assert loaded is not None
    assert loaded.status is RunStatus.COMPLETED
    assert loaded.total_probes == 5


def test_probe_idempotency_and_checkpoint(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    assert storage.has_probe("run-1", "p1", EngineId.PERPLEXITY, "proxy-0") is False
    storage.save_probe(_probe())
    assert storage.has_probe("run-1", "p1", EngineId.PERPLEXITY, "proxy-0") is True
    storage.save_probe(_probe())  # erneut speichern -> kein Duplikat
    assert len(storage.load_probes("run-1")) == 1


def test_load_probes_roundtrip(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.save_probe(_probe("p1"))
    storage.save_probe(_probe("p2"))
    probes = storage.load_probes("run-1")
    assert len(probes) == 2
    assert probes[0].citations[0].url == "https://it-sicherheit.de/nis2"


def test_pages_roundtrip(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    pages = build_sample_inventory()
    storage.save_pages("run-1", pages)
    assert len(storage.load_pages("run-1")) == len(pages)


def test_report_roundtrip(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    report = TopFlopReport(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        n_probes=10,
        n_pages=8,
        top=(
            TopFlopEntry(
                position=1,
                url="https://it-sicherheit.de/nis2",
                citation_count=5,
                citation_rate=0.5,
                best_rank=1,
            ),
        ),
    )
    storage.save_report(report)
    assert storage.load_report("run-1") == report


def _fix_plan() -> FixPlan:
    return FixPlan(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        prompt_version="v1",
        proposals=(
            FixProposal(
                patch_id="px-f1-add_schema",
                finding_id="f1",
                target_url="https://it-sicherheit.de/firewall-grundlagen",
                lever=Lever.ENTITY_CLARITY,
                pyramid_level=PyramidLevel.SUBSTANCE,
                change_type=ChangeType.ADD_SCHEMA,
                proposed_content='{"@type": "Person"}',
                rationale="Autor-Schema fehlt.",
                confidence=0.8,
            ),
        ),
    )


def test_fix_plan_roundtrip_and_projection(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    plan = _fix_plan()
    storage.save_fix_plan(plan)
    assert storage.load_fix_plan("run-1") == plan
    assert storage.load_fix_plan("unknown") is None
    # Projektion in patches-Tabelle (fuer das Dashboard) ist vorhanden:
    rows = storage._fetchall("SELECT patch_id FROM patches WHERE run_id = ?", ("run-1",))
    assert [r["patch_id"] for r in rows] == ["px-f1-add_schema"]
    storage.save_fix_plan(plan)  # idempotent (Upsert), kein Duplikat
    rows = storage._fetchall("SELECT patch_id FROM patches WHERE run_id = ?", ("run-1",))
    assert len(rows) == 1


def test_approvals_roundtrip(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    d = ApprovalDecision(
        patch_id="px-f1-add_schema",
        run_id="run-1",
        approved=True,
        reviewer="cli:--approve-all",
        decided_at=FIXED,
    )
    storage.save_approvals("run-1", [d])
    assert storage.load_approvals("run-1") == [d]
    # Einzel-Upsert ueberschreibt dieselbe (run_id, patch_id):
    storage.save_decision(d.model_copy(update={"approved": False}))
    loaded = storage.load_approvals("run-1")
    assert len(loaded) == 1
    assert loaded[0].approved is False


def test_deploy_result_roundtrip(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    result = DeployResult(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        publisher="mock",
        applied_patch_ids=("px-f1-add_schema",),
        status=DeployStatus.DRY_RUN,
    )
    storage.save_deploy_result(result)
    assert storage.load_deploy_result("run-1") == result
    assert storage.load_deploy_result("unknown") is None


def test_probe_phase_no_collision(tmp_path: Path) -> None:
    # Baseline- und Re-Probe-Zelle mit identischem (prompt/engine/proxy) koexistieren.
    storage = _storage(tmp_path)
    storage.save_probe(_probe(phase=ProbePhase.BASELINE))
    storage.save_probe(_probe(phase=ProbePhase.REPROBE))
    assert len(storage.load_probes("run-1")) == 2  # keine gegenseitige Verdraengung
    assert storage.has_probe("run-1", "p1", EngineId.PERPLEXITY, "proxy-0", ProbePhase.BASELINE)
    assert storage.has_probe("run-1", "p1", EngineId.PERPLEXITY, "proxy-0", ProbePhase.REPROBE)


def test_load_probes_phase_filter(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.save_probe(_probe("p1", phase=ProbePhase.BASELINE))
    storage.save_probe(_probe("p2", phase=ProbePhase.BASELINE))
    storage.save_probe(_probe("p1", phase=ProbePhase.REPROBE))
    assert len(storage.load_probes("run-1", ProbePhase.BASELINE)) == 2
    assert len(storage.load_probes("run-1", ProbePhase.REPROBE)) == 1
    assert len(storage.load_probes("run-1")) == 3  # ohne Filter: alle Phasen


def _effect_report() -> EffectReport:
    hyp = EffectHypothesis(
        hypothesis_id=derive_hypothesis_id("run-1", "px-f1-insert_block"),
        run_id="run-1",
        target_domain="it-sicherheit.de",
        target_url="https://it-sicherheit.de/firewall-grundlagen",
        patch_id="px-f1-insert_block",
        finding_id="f1",
        lever=Lever.FACT_DENSITY,
        pyramid_level=PyramidLevel.SUBSTANCE,
        change_type=ChangeType.INSERT_BLOCK,
        before_citation_rate=0.05,
        after_citation_rate=0.95,
        before_n=240,
        after_n=240,
        delta=0.9,
        direction=EffectDirection.IMPROVED,
        confidence=0.86,
        suspected_cause="x",
        observed_at=FIXED,
    )
    return EffectReport(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        prompt_version="v2",
        reprobe_matrix_size=240,
        mean_delta=0.9,
        n_improved=1,
        hypotheses=(hyp,),
    )


def test_effect_report_roundtrip(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    report = _effect_report()
    storage.save_effect_report(report)
    assert storage.load_effect_report("run-1") == report
    assert storage.load_effect_report("unknown") is None
    storage.delete_run("run-1")
    assert storage.load_effect_report("run-1") is None


def _serp_result(query_id: str = "q01", provider: SerpProvider = SerpProvider.MOCK) -> SerpResult:
    return SerpResult(
        run_id="run-1",
        provider=provider,
        query_id=query_id,
        prompt_id="p01",
        query_text="nis2 anforderungen",
        entries=(RankEntry(url="https://bsi.bund.de/nis2", position=1, title="NIS2"),),
        fetched_at=FIXED,
    )


def test_index_submission_roundtrip(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    result = IndexSubmissionResult(
        run_id="run-1",
        host="it-sicherheit.de",
        urls=("https://it-sicherheit.de/nis2",),
        generated_at=FIXED,
        dry_run=False,
        status=IndexSubmissionStatus.SUBMITTED,
        endpoints=(
            EndpointResult(
                endpoint=IndexingEndpoint.INDEXNOW,
                status=IndexSubmissionStatus.SUBMITTED,
                http_status=202,
                attempts=1,
            ),
        ),
    )
    storage.save_index_submission(result)
    assert storage.load_index_submission("run-1") == result
    assert storage.load_index_submission("unknown") is None
    storage.save_index_submission(result)  # Upsert, kein Duplikat/Fehler
    assert storage.load_index_submission("run-1") == result


def test_serp_result_roundtrip_and_checkpoint(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    assert storage.has_serp_result("run-1", SerpProvider.MOCK, "q01") is False
    storage.save_serp_result(_serp_result())
    assert storage.has_serp_result("run-1", SerpProvider.MOCK, "q01") is True
    storage.save_serp_result(_serp_result())  # idempotent (UNIQUE-Schluessel)
    assert len(storage.load_serp_results("run-1")) == 1
    loaded = storage.load_serp_results("run-1")[0]
    assert loaded == _serp_result()
    assert loaded.entries[0].position == 1


def test_serp_results_provider_filter_and_order(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.save_serp_result(_serp_result("q02"))
    storage.save_serp_result(_serp_result("q01"))
    storage.save_serp_result(_serp_result("q01", provider=SerpProvider.SERPER))
    assert len(storage.load_serp_results("run-1")) == 3  # ohne Filter: alle Provider
    mock_only = storage.load_serp_results("run-1", SerpProvider.MOCK)
    assert [r.query_id for r in mock_only] == ["q01", "q02"]  # sortiert nach query_id
    assert storage.has_serp_result("run-1", SerpProvider.SERPER, "q02") is False


def test_overlap_report_roundtrip(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    report = OverlapReport(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        provider=SerpProvider.MOCK,
        query_set_version="v1",
        n_queries=1,
        mean_jaccard=0.333333,
        mean_ai_in_serp_share=0.5,
        stats=(
            OverlapStat(
                query_id="q01",
                prompt_id="p01",
                jaccard=0.333333,
                ai_in_serp_share=0.5,
                domain_jaccard=0.5,
                target_serp_rank=3,
                target_ai_citation_rate=0.25,
                n_serp_urls=2,
                n_ai_urls=2,
            ),
        ),
    )
    storage.save_overlap_report(report)
    assert storage.load_overlap_report("run-1") == report
    assert storage.load_overlap_report("unknown") is None


def test_delete_run_removes_live_loop_artifacts(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.save_index_submission(
        IndexSubmissionResult(run_id="run-1", host="it-sicherheit.de", generated_at=FIXED)
    )
    storage.save_serp_result(_serp_result())
    storage.save_overlap_report(
        OverlapReport(
            run_id="run-1",
            target_domain="it-sicherheit.de",
            generated_at=FIXED,
            provider=SerpProvider.MOCK,
            query_set_version="v1",
            n_queries=0,
            mean_jaccard=0.0,
            mean_ai_in_serp_share=0.0,
        )
    )
    storage.delete_run("run-1")
    assert storage.load_index_submission("run-1") is None
    assert storage.load_serp_results("run-1") == []
    assert storage.load_overlap_report("run-1") is None


def test_initialize_is_idempotent_with_new_tables(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.save_serp_result(_serp_result())
    storage.initialize()  # erneut aufrufen -> kein Fehler, keine Datenverluste
    assert storage.has_serp_result("run-1", SerpProvider.MOCK, "q01") is True


def test_delete_run_removes_fix_artifacts(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.save_fix_plan(_fix_plan())
    storage.save_decision(
        ApprovalDecision(
            patch_id="px-f1-add_schema",
            run_id="run-1",
            approved=True,
            reviewer="t",
            decided_at=FIXED,
        )
    )
    storage.save_deploy_result(
        DeployResult(
            run_id="run-1", target_domain="it-sicherheit.de", generated_at=FIXED, publisher="mock"
        )
    )
    storage.delete_run("run-1")
    assert storage.load_fix_plan("run-1") is None
    assert storage.load_approvals("run-1") == []
    assert storage.load_deploy_result("run-1") is None
