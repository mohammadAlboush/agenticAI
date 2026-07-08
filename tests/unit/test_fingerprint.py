"""Unit: Report-Fingerprint — inhaltsstabil, laufvariable Felder gehen nicht ein."""

from __future__ import annotations

from datetime import datetime

from geo_audit_loop.domain.audit import AuditFinding, AuditReport, Severity
from geo_audit_loop.domain.competitive import DomainShare, ShareOfVoiceReport
from geo_audit_loop.domain.coverage import CoverageReport, IntentCoverage
from geo_audit_loop.domain.entity import EntityGraphReport, build_entity_graph
from geo_audit_loop.domain.findings import TopFlopEntry, TopFlopReport
from geo_audit_loop.domain.fingerprint import report_fingerprint
from geo_audit_loop.domain.fix import ChangeType, FixPlan, FixProposal
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.domain.inventory import CrawledPage, PageInventory, SchemaInventory
from geo_audit_loop.domain.probe import QueryIntent
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


def _sov(run_id: str = "a", generated_at: datetime = FIXED, count: int = 35) -> ShareOfVoiceReport:
    return ShareOfVoiceReport(
        run_id=run_id,
        target_domain="it-sicherheit.de",
        generated_at=generated_at,
        n_probes=48,
        target_rank=1,
        target_share=0.77,
        shares=(
            DomainShare(
                rank=1,
                domain="it-sicherheit.de",
                citation_count=37,
                citation_rate=0.77,
                is_target=True,
            ),
            DomainShare(
                rank=2,
                domain="bsi.bund.de",
                citation_count=count,
                citation_rate=0.73,
                is_target=False,
            ),
        ),
    )


def test_sov_gated_absent_preserves_fingerprint() -> None:
    # Ohne SoV-Report aendert der neue ``share``-Parameter den Hash NICHT (gated).
    assert report_fingerprint(_topflop(), _patterns()) == report_fingerprint(
        _topflop(), _patterns(), share=None
    )


def test_sov_folded_into_fingerprint() -> None:
    assert report_fingerprint(_topflop()) != report_fingerprint(_topflop(), share=_sov())


def test_sov_volatile_fields_do_not_change_fingerprint() -> None:
    a = report_fingerprint(_topflop("a", FIXED), share=_sov("a", FIXED))
    b = report_fingerprint(_topflop("b", OTHER), share=_sov("b", OTHER))
    assert a == b  # run_id/generated_at gehen nicht in den Hash ein


def test_sov_content_change_changes_fingerprint() -> None:
    a = report_fingerprint(_topflop(), share=_sov(count=35))
    b = report_fingerprint(_topflop(), share=_sov(count=30))
    assert a != b


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


def _fixplan(
    run_id: str = "a", generated_at: datetime = FIXED, content: str = "Block A"
) -> FixPlan:
    return FixPlan(
        run_id=run_id,
        target_domain="it-sicherheit.de",
        generated_at=generated_at,
        prompt_version="v1",
        proposals=(
            FixProposal(
                patch_id="px-f1-insert_block",
                finding_id="f1",
                target_url="/firewall-grundlagen",
                lever=Lever.ANSWER_BLOCKS,
                pyramid_level=PyramidLevel.EXTRACTABILITY,
                change_type=ChangeType.INSERT_BLOCK,
                proposed_content=content,
                rationale="Antwortblock fehlt.",
                confidence=0.8,
            ),
        ),
    )


def test_fixplan_folded_into_fingerprint() -> None:
    without = report_fingerprint(_topflop(), _patterns(), _audit())
    with_fix = report_fingerprint(_topflop(), _patterns(), _audit(), _fixplan())
    assert without != with_fix  # Sprint 3 aendert den Fingerprint


def test_fixplan_stable_across_volatile_fields() -> None:
    a = report_fingerprint(_topflop("a", FIXED), fix_plan=_fixplan("a", FIXED))
    b = report_fingerprint(_topflop("b", OTHER), fix_plan=_fixplan("b", OTHER))
    assert a == b


def test_fixplan_content_change_changes_fingerprint() -> None:
    a = report_fingerprint(_topflop(), fix_plan=_fixplan(content="Block A"))
    b = report_fingerprint(_topflop(), fix_plan=_fixplan(content="Block B"))
    assert a != b


def _coverage(
    run_id: str = "a", generated_at: datetime = FIXED, rate: float = 0.25
) -> CoverageReport:
    return CoverageReport(
        run_id=run_id,
        target_domain="it-sicherheit.de",
        generated_at=generated_at,
        n_probes=240,
        overall_citation_rate=0.5,
        intents=(
            IntentCoverage(
                intent=QueryIntent.HOWTO,
                n_prompts=4,
                n_covered=2,
                coverage_rate=0.5,
                mean_citation_rate=rate,
            ),
        ),
        weakest_intents=(QueryIntent.DEFINITION,),
    )


def test_coverage_gated_out_when_absent() -> None:
    """Ohne Coverage-Argument bleibt der Fingerprint bit-identisch (Sprint-1..4 unveraendert)."""
    without = report_fingerprint(_topflop(), _patterns(), _audit())
    with_none = report_fingerprint(_topflop(), _patterns(), _audit(), coverage=None)
    assert without == with_none


def test_coverage_folded_into_fingerprint() -> None:
    without = report_fingerprint(_topflop(), _patterns(), _audit())
    with_cov = report_fingerprint(_topflop(), _patterns(), _audit(), coverage=_coverage())
    assert without != with_cov  # Session 4 aendert den Fingerprint, sobald Coverage vorliegt


def test_coverage_stable_across_volatile_fields() -> None:
    a = report_fingerprint(_topflop("a", FIXED), coverage=_coverage("a", FIXED))
    b = report_fingerprint(_topflop("b", OTHER), coverage=_coverage("b", OTHER))
    assert a == b


def test_coverage_content_change_changes_fingerprint() -> None:
    a = report_fingerprint(_topflop(), coverage=_coverage(rate=0.25))
    b = report_fingerprint(_topflop(), coverage=_coverage(rate=0.30))
    assert a != b


def _entity_graph(
    run_id: str = "a", generated_at: datetime = FIXED, *, opengraph: bool = True
) -> EntityGraphReport:
    pages = [
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
                has_opengraph=opengraph,
            ),
        )
    ]
    return build_entity_graph("it-sicherheit.de", pages, run_id=run_id, generated_at=generated_at)


def test_entity_graph_gated_out_when_absent() -> None:
    """Ohne Entity-Graph-Argument bleibt der Fingerprint bit-identisch (Sprint 1..4 stabil)."""
    without = report_fingerprint(_topflop(), _patterns(), _audit())
    with_none = report_fingerprint(_topflop(), _patterns(), _audit(), entity_graph=None)
    assert without == with_none


def test_entity_graph_folded_into_fingerprint() -> None:
    without = report_fingerprint(_topflop(), _patterns(), _audit())
    with_eg = report_fingerprint(_topflop(), _patterns(), _audit(), entity_graph=_entity_graph())
    assert without != with_eg  # Session 8 aendert den Fingerprint, sobald der Graph vorliegt


def test_entity_graph_stable_across_volatile_fields() -> None:
    a = report_fingerprint(_topflop("a", FIXED), entity_graph=_entity_graph("a", FIXED))
    b = report_fingerprint(_topflop("b", OTHER), entity_graph=_entity_graph("b", OTHER))
    assert a == b


def test_entity_graph_content_change_changes_fingerprint() -> None:
    a = report_fingerprint(_topflop(), entity_graph=_entity_graph(opengraph=True))
    b = report_fingerprint(_topflop(), entity_graph=_entity_graph(opengraph=False))
    assert a != b
