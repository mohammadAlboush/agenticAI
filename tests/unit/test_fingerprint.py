"""Unit: Report-Fingerprint — inhaltsstabil, laufvariable Felder gehen nicht ein."""

from __future__ import annotations

from datetime import datetime

from geo_audit_loop.domain.audit import AuditFinding, AuditReport, Severity
from geo_audit_loop.domain.findings import TopFlopEntry, TopFlopReport
from geo_audit_loop.domain.fingerprint import report_fingerprint
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.domain.templates import PatternReport, Template

FIXED = datetime(2026, 1, 1, 12, 0, 0)
OTHER = datetime(2026, 6, 11, 8, 30, 0)


def _topflop(run_id: str = "a", generated_at: datetime = FIXED, count: int = 71) -> TopFlopReport:
    return TopFlopReport(
        run_id=run_id,
        target_domain="it-sicherheit.de",
        generated_at=generated_at,
        n_probes=240,
        n_pages=8,
        top=(
            TopFlopEntry(
                position=1, url="/nis2-richtlinie", citation_count=count, citation_rate=0.3
            ),
        ),
        flop=(
            TopFlopEntry(
                position=1, url="/firewall-grundlagen", citation_count=7, citation_rate=0.03
            ),
        ),
    )


def _patterns(run_id: str = "a", generated_at: datetime = FIXED) -> PatternReport:
    return PatternReport(
        run_id=run_id,
        target_domain="it-sicherheit.de",
        generated_at=generated_at,
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


def _audit(run_id: str = "a", generated_at: datetime = FIXED) -> AuditReport:
    return AuditReport(
        run_id=run_id,
        target_domain="it-sicherheit.de",
        generated_at=generated_at,
        findings=(
            AuditFinding(
                finding_id="f1",
                target_url="/firewall-grundlagen",
                lever=Lever.DEFINITION_BLOCKS,
                pyramid_level=PyramidLevel.EXTRACTABILITY,
                severity=Severity.MEDIUM,
                evidence="Keine Definitionsbloecke vorhanden.",
                recommendation="FAQPage-Schema ergaenzen.",
            ),
        ),
    )


def test_same_content_same_fingerprint() -> None:
    a = report_fingerprint(_topflop(), _patterns(), _audit())
    b = report_fingerprint(_topflop(), _patterns(), _audit())
    assert a == b
    assert len(a) == 12


def test_volatile_fields_do_not_change_fingerprint() -> None:
    a = report_fingerprint(_topflop("a", FIXED), _patterns("a", FIXED), _audit("a", FIXED))
    b = report_fingerprint(_topflop("b", OTHER), _patterns("b", OTHER), _audit("b", OTHER))
    assert a == b


def test_content_change_changes_fingerprint() -> None:
    a = report_fingerprint(_topflop(count=71))
    b = report_fingerprint(_topflop(count=70))
    assert a != b


def test_sprint1_only_differs_from_sprint2() -> None:
    a = report_fingerprint(_topflop())
    b = report_fingerprint(_topflop(), _patterns(), _audit())
    assert a != b
