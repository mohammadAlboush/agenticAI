"""Phase-4-Gate: SQLite-Persistenz inkl. Idempotenz/Checkpoint-Resume."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from geo_audit_loop.adapters.sample_data import build_sample_inventory
from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
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
from geo_audit_loop.domain.probe import Citation, EngineId, ProbeResult, ProbeStatus, ProbeUsage
from geo_audit_loop.domain.run import RunRecord, RunStatus

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


def _probe(prompt_id: str = "p1", proxy_label: str = "proxy-0") -> ProbeResult:
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
