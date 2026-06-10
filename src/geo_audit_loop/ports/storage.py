"""Port: persistente Speicherung von Runs, Probes, Seiten und Reports.

Der Port traegt die Idempotenz-/Checkpoint-Faehigkeit (Projektregeln §6): ``has_probe``
erlaubt es dem Sampler, bereits erledigte Probes beim Neustart zu ueberspringen.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from geo_audit_loop.domain.audit import AuditReport
from geo_audit_loop.domain.findings import TopFlopReport
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.probe import EngineId, ProbeResult
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

    def save_probe(self, result: ProbeResult) -> None:
        """Persistiert eine Probe idempotent (UNIQUE run_id/prompt/engine/proxy)."""
        ...

    def has_probe(
        self, run_id: str, prompt_id: str, engine_id: EngineId, proxy_label: str | None
    ) -> bool:
        """Prueft, ob diese Probe-Zelle bereits erledigt ist (Checkpoint-Resume)."""
        ...

    def load_probes(self, run_id: str) -> list[ProbeResult]:
        """Laedt alle Probes eines Runs (fuer Aggregation/Report)."""
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
