"""Unit: GEO-Vokabular + Findings-Priorisierung (reine Domaenenlogik, kein I/O)."""

from __future__ import annotations

from geo_audit_loop.domain.audit import AuditFinding, Severity, prioritize_findings
from geo_audit_loop.domain.geo import LEVER_PYRAMID, Lever, PyramidLevel, pyramid_rank


def _finding(fid: str, lever: Lever, level: PyramidLevel, severity: Severity) -> AuditFinding:
    return AuditFinding(
        finding_id=fid,
        target_url="https://x",
        lever=lever,
        pyramid_level=level,
        severity=severity,
        evidence="e",
        recommendation="r",
    )


def test_prioritize_by_pyramid_then_severity() -> None:
    citation = _finding("b", Lever.QUERY_COVERAGE, PyramidLevel.CITATION, Severity.CRITICAL)
    extract = _finding("c", Lever.ANSWER_BLOCKS, PyramidLevel.EXTRACTABILITY, Severity.MEDIUM)
    access = _finding("a", Lever.CRAWLER_ACCESS, PyramidLevel.ACCESS, Severity.LOW)
    ordered = prioritize_findings([citation, extract, access])
    ranks = [pyramid_rank(f.pyramid_level) for f in ordered]
    assert ranks == sorted(ranks)  # untere Ebene zuerst
    assert ordered[0].pyramid_level is PyramidLevel.ACCESS


def test_every_lever_maps_to_a_pyramid_level() -> None:
    for lever in Lever:
        assert isinstance(LEVER_PYRAMID[lever], PyramidLevel)
