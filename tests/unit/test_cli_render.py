"""Unit: rich-Renderer der CLI — Inhalte vorhanden, leere Reports crashen nicht."""

from __future__ import annotations

from datetime import datetime

from rich.console import Console

from geo_audit_loop.cli.render import (
    render_deploy,
    render_entity_graph,
    render_error,
    render_findings,
    render_fixplan,
    render_header,
    render_hitl,
    render_patterns,
    render_summary,
    render_topflop,
)
from geo_audit_loop.domain.audit import AuditFinding, AuditReport, Severity
from geo_audit_loop.domain.entity import build_entity_graph
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
from geo_audit_loop.domain.inventory import CrawledPage, PageInventory, SchemaInventory
from geo_audit_loop.domain.templates import PatternReport, Template
from geo_audit_loop.observability.cost import CostSnapshot

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _console() -> Console:
    return Console(record=True, width=100)


def _topflop() -> TopFlopReport:
    return TopFlopReport(
        run_id="r1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        n_probes=240,
        n_pages=8,
        top=(
            TopFlopEntry(position=1, url="/nis2-richtlinie", citation_count=71, citation_rate=0.3),
        ),
        flop=(
            TopFlopEntry(
                position=1,
                url="/security-awareness-training",
                citation_count=7,
                citation_rate=0.03,
            ),
        ),
    )


def test_header_contains_run_metadata() -> None:
    console = _console()
    render_header(
        console,
        domain="it-sicherheit.de",
        run_id="abc123",
        seed=42,
        offline=True,
        prompt_version="v1",
        top_n=3,
    )
    text = console.export_text()
    assert "it-sicherheit.de" in text
    assert "OFFLINE" in text
    assert "Seed 42" in text
    assert "abc123" in text


def test_topflop_lists_urls_and_rates() -> None:
    console = _console()
    render_topflop(console, _topflop())
    text = console.export_text()
    assert "/nis2-richtlinie" in text
    assert "/security-awareness-training" in text
    assert "71x" in text
    assert "0.30" in text
    assert "240 Probes" in text


def test_patterns_show_confidence_and_levers() -> None:
    console = _console()
    report = PatternReport(
        run_id="r1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        templates=(
            Template(
                template_id="t1",
                title="Extrahierbarer Antwortblock",
                summary="Antwort direkt unter der H1.",
                levers=(Lever.ANSWER_BLOCKS,),
                pyramid_level=PyramidLevel.EXTRACTABILITY,
                confidence=0.82,
            ),
        ),
    )
    render_patterns(console, report)
    text = console.export_text()
    assert "t1" in text
    assert "Extrahierbarer Antwortblock" in text
    assert "0.82" in text
    assert "Antwortbloecke" in text


def test_findings_show_severity_and_fix() -> None:
    console = _console()
    report = AuditReport(
        run_id="r1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        findings=(
            AuditFinding(
                finding_id="f1",
                target_url="/firewall-grundlagen",
                lever=Lever.DEFINITION_BLOCKS,
                pyramid_level=PyramidLevel.EXTRACTABILITY,
                severity=Severity.HIGH,
                evidence="Keine Definitionsbloecke vorhanden.",
                recommendation="FAQPage-Schema ergaenzen.",
            ),
        ),
    )
    render_findings(console, report)
    text = console.export_text()
    assert "HIGH" in text
    assert "/firewall-grundlagen" in text
    assert "FAQPage-Schema ergaenzen." in text
    assert "Beleg:" in text


def _entity_pages() -> list[PageInventory]:
    return [
        PageInventory(
            page=CrawledPage(
                url="https://it-sicherheit.de/nis2",
                status_code=200,
                canonical="https://it-sicherheit.de/nis2",
                lang="de",
            ),
            schema_inventory=SchemaInventory(
                url="https://it-sicherheit.de/nis2",
                jsonld_types=("Organization",),
                has_opengraph=True,
            ),
        ),
        PageInventory(
            page=CrawledPage(url="https://it-sicherheit.de/firewall", status_code=200),
            schema_inventory=SchemaInventory(url="https://it-sicherheit.de/firewall"),
        ),
    ]


def test_entity_graph_shows_brand_gap_and_jsonld() -> None:
    console = _console()
    report = build_entity_graph(
        "it-sicherheit.de", _entity_pages(), run_id="r1", generated_at=FIXED
    )
    render_entity_graph(console, report)
    text = console.export_text()
    assert "it-sicherheit" in text  # Marken-Name
    assert "Organization" in text  # schema.org-Typ / JSON-LD
    assert "Luecken" in text  # schwache Seite markiert
    assert "@id" in text  # empfohlener JSON-LD-Block


def test_summary_shows_cost_and_fingerprint() -> None:
    console = _console()
    render_summary(
        console,
        snapshot=CostSnapshot(probes=240, total_tokens=39_800, total_usd=0.3115),
        fingerprint="abcdef123456",
        seed=42,
        duration_s=12.3,
    )
    text = console.export_text()
    assert "240 Probes" in text
    assert "abcdef123456" in text
    assert "$0.3115" in text
    assert "reproduzierbar" in text


def _fix_plan() -> FixPlan:
    return FixPlan(
        run_id="r1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        prompt_version="v1",
        proposals=(
            FixProposal(
                patch_id="px-f1-insert_block",
                finding_id="f1",
                target_url="https://www.it-sicherheit.de/firewall-grundlagen",
                lever=Lever.ANSWER_BLOCKS,
                pyramid_level=PyramidLevel.EXTRACTABILITY,
                change_type=ChangeType.INSERT_BLOCK,
                proposed_content="Praegnanter Antwortblock direkt unter der H1.",
                rationale="Template t1 verlangt einen extrahierbaren Antwortblock.",
                confidence=0.78,
            ),
        ),
    )


def test_fixplan_shows_patch_and_confidence() -> None:
    console = _console()
    render_fixplan(console, _fix_plan())
    text = console.export_text()
    assert "px-f1-insert_block" not in text  # patch_id steht erst im HITL-Block
    assert "/firewall-grundlagen" in text
    assert "0.78" in text
    assert "Antwortbloecke" in text
    assert "Patches" in text


def test_hitl_shows_decision_and_gate_note() -> None:
    console = _console()
    plan = _fix_plan()
    decisions = {
        "px-f1-insert_block": ApprovalDecision(
            patch_id="px-f1-insert_block",
            run_id="r1",
            approved=True,
            reviewer="cli:--approve-all",
            decided_at=FIXED,
        )
    }
    render_hitl(console, plan, decisions)
    text = console.export_text()
    assert "FREIGABE" in text
    assert "cli:--approve-all" in text
    assert "Kein Deploy ohne Freigabe" in text


def test_deploy_shows_dry_run_safety() -> None:
    console = _console()
    result = DeployResult(
        run_id="r1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        publisher="mock",
        applied_patch_ids=("px-f1-insert_block",),
        status=DeployStatus.DRY_RUN,
        detail="Dry-Run.",
    )
    render_deploy(console, result)
    text = console.export_text()
    assert "DRY-RUN" in text
    assert "KEINE EXTERNEN WRITES" in text
    assert "1 angewandt" in text


def test_empty_reports_do_not_crash() -> None:
    console = _console()
    empty_topflop = TopFlopReport(
        run_id="r1",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        n_probes=0,
        n_pages=0,
    )
    empty_patterns = PatternReport(
        run_id="r1", target_domain="it-sicherheit.de", generated_at=FIXED
    )
    empty_audit = AuditReport(run_id="r1", target_domain="it-sicherheit.de", generated_at=FIXED)
    empty_entity = build_entity_graph("it-sicherheit.de", [], run_id="r1", generated_at=FIXED)
    render_topflop(console, empty_topflop)
    render_patterns(console, empty_patterns)
    render_findings(console, empty_audit)
    render_entity_graph(console, empty_entity)
    render_error(console, title="Run fehlgeschlagen", message="Testfehler")
    assert console.export_text()
