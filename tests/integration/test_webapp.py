"""Integration: Run-Monitor-API gegen eine temporaere SQLite (kein Netz, kein Server)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from starlette.testclient import TestClient

from geo_audit_loop.adapters.sample_data import build_sample_inventory
from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.audit import AuditFinding, AuditReport, Severity
from geo_audit_loop.domain.effect import EffectDirection, EffectHypothesis, EffectReport
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
from geo_audit_loop.domain.probe import Citation, EngineId, ProbeResult, ProbeUsage
from geo_audit_loop.domain.run import RunRecord, RunStatus
from geo_audit_loop.domain.templates import PatternReport, Template
from geo_audit_loop.webapp.app import create_app

FIXED = datetime(2026, 1, 1, 12, 0, 0)
RUN = "run-web"


def _settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "geo.db")


def _seed(tmp_path: Path, *, with_results: bool = True) -> None:
    storage = SqliteStorage(tmp_path / "geo.db")
    storage.initialize()
    storage.save_run(
        RunRecord(
            run_id=RUN,
            target_domain="it-sicherheit.de",
            status=RunStatus.COMPLETED if with_results else RunStatus.RUNNING,
            started_at=FIXED,
            seed=42,
            prompt_set_version="v1",
            config_hash="hash",
        )
    )
    storage.save_probe(
        ProbeResult(
            run_id=RUN,
            engine_id=EngineId.PERPLEXITY,
            model="m",
            prompt_id="p01",
            prompt_version="v1",
            proxy_label="proxy-0",
            answer_text="Antwort mit Quelle.",
            citations=(
                Citation(
                    url="https://www.it-sicherheit.de/nis2", engine=EngineId.PERPLEXITY, rank=2
                ),
            ),
            target_cited=True,
            target_rank=2,
            usage=ProbeUsage(total_tokens=42),
            probed_at=FIXED,
        )
    )
    storage.save_pages(RUN, build_sample_inventory())
    if not with_results:
        storage.close()
        return
    storage.save_report(
        TopFlopReport(
            run_id=RUN,
            target_domain="it-sicherheit.de",
            generated_at=FIXED,
            n_probes=1,
            n_pages=8,
            top=(
                TopFlopEntry(
                    position=1, url="/nis2-richtlinie", citation_count=7, citation_rate=0.3
                ),
            ),
        )
    )
    storage.save_pattern_report(
        PatternReport(
            run_id=RUN,
            target_domain="it-sicherheit.de",
            generated_at=FIXED,
            templates=(
                Template(
                    template_id="t1",
                    title="Antwortblock",
                    summary="Antwort nach H1.",
                    levers=(Lever.ANSWER_BLOCKS,),
                    pyramid_level=PyramidLevel.EXTRACTABILITY,
                    confidence=0.8,
                ),
            ),
        )
    )
    storage.save_audit_report(
        AuditReport(
            run_id=RUN,
            target_domain="it-sicherheit.de",
            generated_at=FIXED,
            findings=(
                AuditFinding(
                    finding_id="f1",
                    target_url="/firewall-grundlagen",
                    lever=Lever.DEFINITION_BLOCKS,
                    pyramid_level=PyramidLevel.EXTRACTABILITY,
                    severity=Severity.MEDIUM,
                    evidence="Keine Definitionsbloecke.",
                    recommendation="FAQPage-Schema ergaenzen.",
                ),
            ),
        )
    )
    storage.save_fix_plan(
        FixPlan(
            run_id=RUN,
            target_domain="it-sicherheit.de",
            generated_at=FIXED,
            prompt_version="v1",
            proposals=(
                FixProposal(
                    patch_id="px-f1-add_schema",
                    finding_id="f1",
                    target_url="/firewall-grundlagen",
                    lever=Lever.DEFINITION_BLOCKS,
                    pyramid_level=PyramidLevel.EXTRACTABILITY,
                    change_type=ChangeType.ADD_SCHEMA,
                    proposed_content='{"@type": "FAQPage"}',
                    rationale="Template t1 verlangt FAQ-Schema.",
                    confidence=0.74,
                ),
            ),
        )
    )
    storage.save_decision(
        ApprovalDecision(
            patch_id="px-f1-add_schema",
            run_id=RUN,
            approved=True,
            reviewer="cli:--approve-all",
            decided_at=FIXED,
        )
    )
    storage.save_deploy_result(
        DeployResult(
            run_id=RUN,
            target_domain="it-sicherheit.de",
            generated_at=FIXED,
            publisher="mock",
            applied_patch_ids=("px-f1-add_schema",),
            status=DeployStatus.DRY_RUN,
        )
    )
    storage.save_effect_report(
        EffectReport(
            run_id=RUN,
            target_domain="it-sicherheit.de",
            generated_at=FIXED,
            prompt_version="v2",
            reprobe_matrix_size=1,
            mean_delta=0.9,
            n_improved=1,
            hypotheses=(
                EffectHypothesis(
                    hypothesis_id="eh-run-web-px-f1-add_schema",
                    run_id=RUN,
                    target_domain="it-sicherheit.de",
                    target_url="/firewall-grundlagen",
                    patch_id="px-f1-add_schema",
                    finding_id="f1",
                    lever=Lever.DEFINITION_BLOCKS,
                    pyramid_level=PyramidLevel.EXTRACTABILITY,
                    change_type=ChangeType.ADD_SCHEMA,
                    before_citation_rate=0.05,
                    after_citation_rate=0.95,
                    before_n=1,
                    after_n=1,
                    delta=0.9,
                    direction=EffectDirection.IMPROVED,
                    confidence=0.6,
                    suspected_cause="x",
                    observed_at=FIXED,
                ),
            ),
        )
    )
    storage.close()


def test_state_empty_db(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    assert client.get("/api/state").json() == {"run": None}
    assert client.get("/api/matrix").json()["cells"] == []
    assert client.get("/api/pages").json() == {"pages": []}
    assert client.get("/").status_code == 200


def test_state_with_completed_run(tmp_path: Path) -> None:
    _seed(tmp_path)
    client = TestClient(create_app(_settings(tmp_path)))
    state = client.get("/api/state").json()
    assert state["run"]["run_id"] == RUN
    assert state["run"]["status"] == "completed"
    assert state["n_probes"] == 1
    assert state["n_pages"] == 8
    assert state["n_templates"] == 1
    assert state["n_findings"] == 1
    # erwartete Probes werden aus den real genutzten Proxy-Labels abgeleitet (hier: 1 IP)
    assert state["expected_probes"] == 4 * 12 * 1
    assert isinstance(state["fingerprint"], str) and len(state["fingerprint"]) == 12


def test_matrix_and_prompt_texts(tmp_path: Path) -> None:
    _seed(tmp_path)
    client = TestClient(create_app(_settings(tmp_path)))
    matrix = client.get("/api/matrix").json()
    assert matrix["run_id"] == RUN
    assert len(matrix["prompts"]) == 12  # Probe-Set v1
    assert all(p["text"] for p in matrix["prompts"])
    assert matrix["cells"][0] == {
        "prompt": "p01",
        "engine": "perplexity",
        "proxy": "proxy-0",
        "cited": True,
        "rank": 2,
        "status": "ok",
    }
    assert matrix["engine_rates"]["perplexity"] == 1.0


def test_probe_detail_and_results(tmp_path: Path) -> None:
    _seed(tmp_path)
    client = TestClient(create_app(_settings(tmp_path)))
    detail = client.get("/api/probe?prompt=p01&engine=perplexity&proxy=proxy-0").json()
    assert detail["answer_text"] == "Antwort mit Quelle."
    assert detail["prompt_text"]
    assert detail["citations"][0]["rank"] == 2
    assert client.get("/api/probe?prompt=p99&engine=perplexity&proxy=x").status_code == 404
    results = client.get("/api/results").json()
    assert results["report"]["top"][0]["url"] == "/nis2-richtlinie"
    assert results["patterns"]["templates"][0]["template_id"] == "t1"
    assert results["audit"]["findings"][0]["severity"] == "medium"
    # Sprint 3: Fix-Plan + Deploy-Ergebnis sind read-only verfuegbar
    assert results["fix_plan"]["proposals"][0]["patch_id"] == "px-f1-add_schema"
    assert results["deploy"]["dry_run"] is True
    assert results["deploy"]["applied_patch_ids"] == ["px-f1-add_schema"]
    # Live-Loop: der overlap-Key ist immer vorhanden (None ohne SERP-Provider).
    assert "overlap" in results
    assert results["overlap"] is None


def test_state_surfaces_sprint3_counts(tmp_path: Path) -> None:
    _seed(tmp_path)
    client = TestClient(create_app(_settings(tmp_path)))
    state = client.get("/api/state").json()
    assert state["n_proposals"] == 1
    assert state["deploy_status"] == "dry_run"


def test_results_and_state_surface_effect(tmp_path: Path) -> None:
    _seed(tmp_path)
    client = TestClient(create_app(_settings(tmp_path)))
    effect = client.get("/api/results").json()["effect"]
    assert effect["n_improved"] == 1
    assert effect["hypotheses"][0]["patch_id"] == "px-f1-add_schema"
    state = client.get("/api/state").json()
    assert state["n_hypotheses"] == 1
    assert state["n_improved"] == 1
    assert state["mean_delta"] == 0.9


def test_start_run_with_learn_spawns_learn_flag(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def spawn(args: list[str], env: dict[str, str]) -> _FakeProc:
        captured["args"] = args
        return _FakeProc()

    client = TestClient(create_app(_settings(tmp_path), spawn=spawn))
    response = client.post("/api/runs", json={"domain": "it-sicherheit.de", "learn": True})
    assert response.status_code == 201
    args = captured["args"]
    assert isinstance(args, list)
    assert "--learn" in args and "--approve-all" in args


def test_start_run_with_fix_spawns_fix_flags(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def spawn(args: list[str], env: dict[str, str]) -> _FakeProc:
        captured["args"] = args
        return _FakeProc()

    client = TestClient(create_app(_settings(tmp_path), spawn=spawn))
    response = client.post(
        "/api/runs", json={"domain": "it-sicherheit.de", "explain": True, "fix": True}
    )
    assert response.status_code == 201
    args = captured["args"]
    assert isinstance(args, list)
    assert "--fix" in args and "--approve-all" in args


def test_running_run_has_no_fingerprint(tmp_path: Path) -> None:
    _seed(tmp_path, with_results=False)
    client = TestClient(create_app(_settings(tmp_path)))
    state = client.get("/api/state").json()
    assert state["run"]["status"] == "running"
    assert state["fingerprint"] is None
    assert state["n_templates"] is None


# --- Steuerzentrale (Start/Stop/Verlauf/Loeschen) --------------------------------


class _FakeProc:
    def __init__(self) -> None:
        self.terminated = False

    def poll(self) -> int | None:
        return 1 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True


def test_config_reports_available_keys(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "geo.db", google_api_key="g", saia_api_key="s")
    client = TestClient(create_app(settings))
    cfg = client.get("/api/config").json()
    assert cfg["live_engines_available"] == ["gemini"]
    assert cfg["reasoning_available"] == ["mock", "saia"]
    assert cfg["defaults"]["domain"] == "it-sicherheit.de"


def test_start_run_spawns_cli_with_expected_args(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def spawn(args: list[str], env: dict[str, str]) -> _FakeProc:
        captured["args"] = args
        captured["env"] = env
        return _FakeProc()

    client = TestClient(create_app(_settings(tmp_path), spawn=spawn))
    response = client.post(
        "/api/runs",
        json={
            "domain": "it-sicherheit.de",
            "offline": False,
            "explain": True,
            "top_n": 3,
            "seed": 7,
            "n_proxy_ips": 1,
            "live_engines": ["gemini"],
            "reasoning_provider": "saia",
        },
    )
    assert response.status_code == 201
    run_id = response.json()["run_id"]
    args = captured["args"]
    assert isinstance(args, list)
    assert "-m" in args and "geo_audit_loop" in args
    assert "--live" in args and "--explain" in args
    assert args[args.index("--run-id") + 1] == run_id
    assert args[args.index("--seed") + 1] == "7"
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["GEO_LIVE_ENGINES"] == "gemini"
    assert env["GEO_REASONING_PROVIDER"] == "saia"
    assert env["GEO_N_PROXY_IPS"] == "1"


def test_start_run_validates_input(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path), spawn=lambda a, e: _FakeProc()))
    assert client.post("/api/runs", json={"domain": ""}).status_code == 400
    bad_engine = client.post(
        "/api/runs", json={"domain": "x.de", "offline": False, "live_engines": ["chatgpt"]}
    )
    assert bad_engine.status_code == 400
    bad_reasoning = client.post("/api/runs", json={"domain": "x.de", "reasoning_provider": "gpt"})
    assert bad_reasoning.status_code == 400
    # Domain-Whitelist haelt Sonderzeichen ab (kein Argument-Schmuggel/XSS-Vektor).
    assert client.post("/api/runs", json={"domain": "<img src=x>"}).status_code == 400
    assert client.post("/api/runs", json={"domain": "evil.de; rm -rf"}).status_code == 400


def test_stop_marks_run_aborted(tmp_path: Path) -> None:
    proc = _FakeProc()
    client = TestClient(create_app(_settings(tmp_path), spawn=lambda a, e: proc))
    run_id = client.post("/api/runs", json={"domain": "it-sicherheit.de"}).json()["run_id"]
    # Run-Eintrag simulieren (der echte Subprozess wuerde ihn anlegen)
    storage = SqliteStorage(tmp_path / "geo.db")
    storage.initialize()
    storage.save_run(
        RunRecord(
            run_id=run_id,
            target_domain="it-sicherheit.de",
            status=RunStatus.RUNNING,
            started_at=FIXED,
            seed=42,
            prompt_set_version="v1",
            config_hash="h",
        )
    )
    storage.close()
    response = client.post(f"/api/runs/{run_id}/stop")
    assert response.status_code == 200
    assert proc.terminated is True
    state = client.get(f"/api/state?run={run_id}").json()
    assert state["run"]["status"] == "aborted"


def test_delete_run_blocked_while_running_then_allowed(tmp_path: Path) -> None:
    _seed(tmp_path, with_results=False)  # Status RUNNING
    client = TestClient(create_app(_settings(tmp_path)))
    assert client.delete(f"/api/runs/{RUN}").status_code == 409
    client.post(f"/api/runs/{RUN}/stop")  # markiert ABORTED (kein Prozess vorhanden)
    assert client.delete(f"/api/runs/{RUN}").status_code == 200
    assert client.get("/api/runs").json()["runs"] == []
    assert client.delete("/api/runs/unbekannt").status_code == 404


def test_run_selection_via_query_param(tmp_path: Path) -> None:
    _seed(tmp_path)
    storage = SqliteStorage(tmp_path / "geo.db")
    storage.initialize()
    storage.save_run(
        RunRecord(
            run_id="neuer",
            target_domain="other.de",
            status=RunStatus.COMPLETED,
            started_at=datetime(2026, 2, 1, 12, 0, 0),
            seed=1,
            prompt_set_version="v1",
            config_hash="h",
        )
    )
    storage.close()
    client = TestClient(create_app(_settings(tmp_path)))
    assert client.get("/api/state").json()["run"]["run_id"] == "neuer"  # neuester
    assert client.get(f"/api/state?run={RUN}").json()["run"]["run_id"] == RUN
    assert client.get(f"/api/matrix?run={RUN}").json()["run_id"] == RUN
    runs = client.get("/api/runs").json()["runs"]
    assert [r["run_id"] for r in runs] == ["neuer", RUN]
