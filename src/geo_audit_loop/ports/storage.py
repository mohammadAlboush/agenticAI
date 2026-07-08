"""Port: persistente Speicherung von Runs, Probes, Seiten und Reports.

Der Port traegt die Idempotenz-/Checkpoint-Faehigkeit (Projektregeln §6): ``has_probe``
erlaubt es dem Sampler, bereits erledigte Probes beim Neustart zu ueberspringen.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from geo_audit_loop.domain.audit import AuditReport
from geo_audit_loop.domain.competitive import ShareOfVoiceReport
from geo_audit_loop.domain.coverage import CoverageReport
from geo_audit_loop.domain.effect import EffectReport
from geo_audit_loop.domain.entity import EntityGraphReport
from geo_audit_loop.domain.findings import TopFlopReport
from geo_audit_loop.domain.fix import ApprovalDecision, DeployResult, FixPlan
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.probe import EngineId, ProbePhase, ProbeResult
from geo_audit_loop.domain.run import RunRecord
from geo_audit_loop.domain.templates import PatternReport


@runtime_checkable
class StoragePort(Protocol):
    """Abstrakte Persistenz fuer alle Run-Artefakte (Implementierung: SQLite)."""

    def initialize(self) -> None:
        """Legt das Schema an, falls noch nicht vorhanden (idempotent)."""
        ...

    def save_run(self, run: RunRecord) -> None:
        """Persistiert einen neuen Run (oder ersetzt ihn bei gleicher run_id)."""
        ...

    def update_run(self, run: RunRecord) -> None:
        """Aktualisiert Status/Kennzahlen eines bestehenden Runs."""
        ...

    def load_run(self, run_id: str) -> RunRecord | None:
        """Laedt einen Run oder ``None``, falls unbekannt."""
        ...

    def list_runs(self) -> list[RunRecord]:
        """Listet alle Runs, neuester zuerst (fuer den Run-Monitor)."""
        ...

    def delete_run(self, run_id: str) -> None:
        """Loescht einen Run samt aller Artefakte (Dashboard-Verwaltung)."""
        ...

    def save_probe(self, result: ProbeResult) -> None:
        """Persistiert eine Probe idempotent (UNIQUE run_id/prompt/engine/proxy/phase)."""
        ...

    def has_probe(
        self,
        run_id: str,
        prompt_id: str,
        engine_id: EngineId,
        proxy_label: str | None,
        phase: ProbePhase = ProbePhase.BASELINE,
    ) -> bool:
        """Prueft, ob diese Probe-Zelle (inkl. Phase) bereits erledigt ist (Checkpoint-Resume)."""
        ...

    def load_probes(self, run_id: str, phase: ProbePhase | None = None) -> list[ProbeResult]:
        """Laedt die Probes eines Runs (optional auf eine Phase gefiltert; sonst alle)."""
        ...

    def save_pages(self, run_id: str, pages: list[PageInventory]) -> None:
        """Persistiert das gecrawlte Seiten-Inventar eines Runs."""
        ...

    def load_pages(self, run_id: str) -> list[PageInventory]:
        """Laedt das Seiten-Inventar eines Runs."""
        ...

    def save_report(self, report: TopFlopReport) -> None:
        """Persistiert den Top/Flop-Report eines Runs."""
        ...

    def load_report(self, run_id: str) -> TopFlopReport | None:
        """Laedt den Top/Flop-Report eines Runs oder ``None``."""
        ...

    # --- Sprint-2-Lern-Artefakte ---
    def save_pattern_report(self, report: PatternReport) -> None:
        """Persistiert die geminten Templates eines Runs (Upsert ueber run_id)."""
        ...

    def load_pattern_report(self, run_id: str) -> PatternReport | None:
        """Laedt den PatternReport eines Runs oder ``None``."""
        ...

    def save_audit_report(self, report: AuditReport) -> None:
        """Persistiert die Audit-Findings eines Runs (Upsert ueber run_id)."""
        ...

    def load_audit_report(self, run_id: str) -> AuditReport | None:
        """Laedt den AuditReport eines Runs oder ``None``."""
        ...

    def append_reasoning_log(
        self, run_id: str, task: str, model: str, prompt_version: str, raw_text: str
    ) -> None:
        """Haengt die rohe LLM-Antwort eines Reasoning-Schritts an (Auditierbarkeit/Replay)."""
        ...

    # --- Sprint-3-Fix-/Deploy-Artefakte ---
    def save_fix_plan(self, plan: FixPlan) -> None:
        """Persistiert den Fix-Plan eines Runs (Upsert ueber run_id) + Patch-Projektion."""
        ...

    def load_fix_plan(self, run_id: str) -> FixPlan | None:
        """Laedt den FixPlan eines Runs oder ``None``."""
        ...

    def save_decision(self, decision: ApprovalDecision) -> None:
        """Persistiert eine einzelne HITL-Entscheidung (Upsert ueber run_id/patch_id)."""
        ...

    def save_approvals(self, run_id: str, decisions: Sequence[ApprovalDecision]) -> None:
        """Persistiert mehrere HITL-Entscheidungen eines Runs (Upsert je Patch)."""
        ...

    def load_approvals(self, run_id: str) -> list[ApprovalDecision]:
        """Laedt alle HITL-Entscheidungen eines Runs."""
        ...

    def save_deploy_result(self, result: DeployResult) -> None:
        """Persistiert das Deploy-Ergebnis eines Runs (Upsert ueber run_id)."""
        ...

    def load_deploy_result(self, run_id: str) -> DeployResult | None:
        """Laedt das Deploy-Ergebnis eines Runs oder ``None``."""
        ...

    # --- Sprint-4-Effekt-/Lern-Artefakte ---
    def save_effect_report(self, report: EffectReport) -> None:
        """Persistiert den Effekt-Report eines Runs (Upsert ueber run_id)."""
        ...

    def load_effect_report(self, run_id: str) -> EffectReport | None:
        """Laedt den EffectReport eines Runs oder ``None``."""
        ...

    # --- Session-3-Wettbewerbs-Artefakt (Share of Voice) ---
    def save_sov_report(self, report: ShareOfVoiceReport) -> None:
        """Persistiert den Share-of-Voice-Report eines Runs (Upsert ueber run_id)."""
        ...

    def load_sov_report(self, run_id: str) -> ShareOfVoiceReport | None:
        """Laedt den Share-of-Voice-Report eines Runs oder ``None``."""

    # --- Session-4-Query-Intent-Coverage-Artefakt ---
    def save_coverage_report(self, report: CoverageReport) -> None:
        """Persistiert den Query-Intent-Coverage-Report eines Runs (Upsert ueber run_id)."""
        ...

    def load_coverage_report(self, run_id: str) -> CoverageReport | None:
        """Laedt den CoverageReport eines Runs oder ``None``."""
        ...

    # --- Session-8-Entity-/Knowledge-Graph-Artefakt ---
    def save_entity_graph(self, report: EntityGraphReport) -> None:
        """Persistiert den Entity-/Knowledge-Graph-Report eines Runs (Upsert ueber run_id)."""
        ...

    def load_entity_graph(self, run_id: str) -> EntityGraphReport | None:
        """Laedt den EntityGraphReport eines Runs oder ``None``."""
        ...
