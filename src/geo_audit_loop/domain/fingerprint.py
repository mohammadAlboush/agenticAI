"""Report-Fingerprint: inhaltsstabiler Hash ueber die Ergebnis-Contracts eines Runs.

Der Fingerprint ist der sichtbare Determinismus-Beweis (Projektregeln §7): gleicher
Seed ⇒ gleicher Fingerprint, obwohl ``run_id`` und ``generated_at`` pro Lauf variieren.
Er ergaenzt ``Settings.run_fingerprint()`` (Hash der Eingangs-Konfiguration) um den
Hash der Ausgangs-Daten.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from geo_audit_loop.domain.audit import AuditReport
from geo_audit_loop.domain.findings import TopFlopReport
from geo_audit_loop.domain.fix import FixPlan
from geo_audit_loop.domain.templates import PatternReport

#: Felder, die pro Lauf variieren und deshalb NICHT in den Hash eingehen.
_VOLATILE_FIELDS: Final[set[str]] = {"run_id", "generated_at"}


def report_fingerprint(
    report: TopFlopReport,
    patterns: PatternReport | None = None,
    audit: AuditReport | None = None,
    fix_plan: FixPlan | None = None,
) -> str:
    """Berechnet den inhaltsstabilen Fingerprint eines Runs (12 Hex-Zeichen).

    Args:
        report: Der Top/Flop-Report der Messung (Sprint 1).
        patterns: Optional der Pattern-Report des Lern-Loops (Sprint 2).
        audit: Optional der Audit-Report des Lern-Loops (Sprint 2).
        fix_plan: Optional der Fix-Plan (Sprint 3). ``ApprovalDecision``/``DeployResult``
            gehen bewusst NICHT ein — sie tragen laufvariable Zeitstempel/Reviewer.

    Returns:
        Die ersten 12 Hex-Zeichen des SHA-256 ueber das kanonische JSON der
        Reports, ohne die laufvariablen Felder ``run_id``/``generated_at``.
    """
    payload = {
        "topflop": report.model_dump(mode="json", exclude=_VOLATILE_FIELDS),
        "patterns": (
            patterns.model_dump(mode="json", exclude=_VOLATILE_FIELDS)
            if patterns is not None
            else None
        ),
        "audit": (
            audit.model_dump(mode="json", exclude=_VOLATILE_FIELDS) if audit is not None else None
        ),
        "fixplan": (
            fix_plan.model_dump(mode="json", exclude=_VOLATILE_FIELDS)
            if fix_plan is not None
            else None
        ),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
