"""Audit-Contracts: Schwachstellen-Befund und priorisierter Audit-Report (GEO-Auditor).

Jeder ``AuditFinding`` traegt Beleg, betroffenen ``Lever`` und ``PyramidLevel`` und ist
optional an ein ``Template`` gebunden. Priorisiert wird nach der Citation-Pyramide:
ein Defizit auf einer unteren Ebene wiegt schwerer als kosmetische Feinheiten oben.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Final

from pydantic import Field

from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.geo import Lever, PyramidLevel, pyramid_rank


class Severity(StrEnum):
    """Schweregrad eines Findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_SEVERITY_RANK: Final[dict[Severity, int]] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


class AuditFinding(FrozenModel):
    """Eine Schwachstelle einer Seite, verankert in Hebel + Pyramide-Ebene + Beleg."""

    finding_id: str = Field(min_length=1)
    target_url: str = Field(min_length=1)
    lever: Lever
    pyramid_level: PyramidLevel
    severity: Severity
    evidence: str = Field(min_length=1)  # Beleg: Stelle/Merkmal im Inventar
    recommendation: str = Field(min_length=1)
    template_id: str | None = None  # orientierendes Template (Finding -> Hebel -> Template)


class AuditReport(FrozenModel):
    """Ergebnis des GEO-Auditors: priorisierte Findings ueber die Flop-Seiten."""

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    generated_at: datetime
    audited_urls: tuple[str, ...] = ()
    findings: tuple[AuditFinding, ...] = ()


def prioritize_findings(findings: Iterable[AuditFinding]) -> tuple[AuditFinding, ...]:
    """Sortiert Findings: untere Pyramide-Ebene zuerst, dann Schweregrad (geo-strategy)."""
    return tuple(
        sorted(
            findings,
            key=lambda f: (
                pyramid_rank(f.pyramid_level),
                _SEVERITY_RANK[f.severity],
                f.target_url,
                f.finding_id,
            ),
        )
    )
