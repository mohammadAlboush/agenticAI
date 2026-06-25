"""Unit: rich-Renderer der CLI — Inhalte vorhanden, leere Reports crashen nicht."""

from __future__ import annotations

from datetime import datetime

from rich.console import Console

from geo_audit_loop.cli.render import (
    render_error,
    render_findings,
    render_header,
    render_patterns,
    render_summary,
    render_topflop,
)
from geo_audit_loop.domain.audit import AuditFinding, AuditReport, Severity
from geo_audit_loop.domain.findings import TopFlopEntry, TopFlopReport
from geo_audit_loop.domain.geo import Lever, PyramidLevel
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
    render_topflop(console, empty_topflop)
    render_patterns(console, empty_patterns)
    render_findings(console, empty_audit)
    render_error(console, title="Run fehlgeschlagen", message="Testfehler")
    assert console.export_text()
