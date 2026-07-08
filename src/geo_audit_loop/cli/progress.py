"""Live-Schrittanzeige des Flows (rich) + Stummschaltung der CrewAI-Konsole.

Der ``FlowProgressListener`` haengt sich an den CrewAI-Event-Bus und uebersetzt die
``MethodExecutionStarted/Finished``-Events des Flows in eine ruhige rich-Anzeige:
Spinner waehrend des Schritts, danach Haekchen + Dauer + Kennzahl. Die rohen
CrewAI-Flow-Panels werden fuer die Demo per ``silence_crewai_console()`` abgeschaltet.
"""

from __future__ import annotations

import io
import time
from typing import TYPE_CHECKING, Any, Final

from crewai.events import BaseEventListener
from crewai.events.types.flow_events import (
    MethodExecutionFinishedEvent,
    MethodExecutionStartedEvent,
)
from rich.progress import Progress, SpinnerColumn, TaskID, TextColumn
from rich.text import Text

from geo_audit_loop.cli.render import ACCENT, GREY
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.orchestration.sprint1_flow import Sprint1Pipeline
from geo_audit_loop.orchestration.sprint2_flow import Sprint2Pipeline
from geo_audit_loop.orchestration.sprint3_flow import Sprint3Pipeline
from geo_audit_loop.orchestration.sprint4_flow import Sprint4Pipeline

if TYPE_CHECKING:
    from crewai.events.event_bus import CrewAIEventsBus
    from rich.console import Console

#: Deutsche Labels der Flow-Schritte (Sprint-1- bis Sprint-4-Flow).
_STEP_LABELS: Final[dict[str, str]] = {
    "sample": "Probe-Matrix sampeln (Engines x Prompts x IPs)",
    "crawl_and_report": "Inventar crawlen + Top/Flop-Report",
    "mine_patterns": "Pattern-Miner — Muster der Top-Seiten",
    "audit_flops": "GEO-Auditor — Flop-Seiten pruefen",
    "retrieve_memory": "Gedaechtnis — fruehere Effekte abrufen",
    "propose_fixes": "Fix-Agent — Patches ableiten",
    "await_approval": "Human-in-the-Loop — Freigabe",
    "apply_patches": "Deploy — Patches anwenden (Dry-Run)",
    "reprobe_and_learn": "Effekt re-proben + ins Gedaechtnis schreiben",
}


def silence_crewai_console() -> None:
    """Schaltet die rohe CrewAI-Konsolenausgabe ab (Flow-Panels + Flow-Logzeilen).

    Die Flow-Panels umgehen das ``verbose``-Flag des Formatters
    (``print_panel(..., is_flow=True)``), und ``Flow._log_flow_event`` schreibt
    direkt auf ``formatter.console`` — deshalb wird die Formatter-Console auf
    eine Null-Console (StringIO) umgeleitet. Muss VOR der Flow-Konstruktion
    laufen, weil bereits das ``FlowCreatedEvent`` ein Panel druckt.
    """
    from crewai.events.event_listener import event_listener
    from rich.console import Console as RichConsole

    event_listener.formatter.verbose = False
    event_listener.formatter.console = RichConsole(file=io.StringIO(), width=120)


def build_progress(console: Console) -> Progress:
    """Baut die rich-Progress-Anzeige fuer die Flow-Schritte."""
    return Progress(
        SpinnerColumn(style=ACCENT, finished_text=Text("✓", style=f"bold {ACCENT}")),
        TextColumn("{task.description}"),
        console=console,
    )


class FlowProgressListener(BaseEventListener):
    """Uebersetzt Flow-Events in rich-Statuszeilen (ein Listener pro CLI-Prozess)."""

    def __init__(
        self,
        *,
        progress: Progress,
        pipeline: Sprint1Pipeline | Sprint2Pipeline | Sprint3Pipeline | Sprint4Pipeline,
        cost_tracker: CostTracker,
    ) -> None:
        # Attribute VOR super().__init__() setzen: die Basisklasse registriert die
        # Handler sofort am globalen Bus.
        self._progress = progress
        self._pipeline = pipeline
        self._cost = cost_tracker
        self._tasks: dict[str, TaskID] = {}
        self._started_at: dict[str, float] = {}
        super().__init__()

    def setup_listeners(self, crewai_event_bus: CrewAIEventsBus) -> None:
        """Registriert die Handler fuer Start/Ende eines Flow-Schritts."""

        @crewai_event_bus.on(MethodExecutionStartedEvent)
        def _on_started(source: Any, event: MethodExecutionStartedEvent) -> None:
            self._step_started(event.method_name)

        @crewai_event_bus.on(MethodExecutionFinishedEvent)
        def _on_finished(source: Any, event: MethodExecutionFinishedEvent) -> None:
            self._step_finished(event.method_name)

    def _label(self, method_name: str) -> str:
        return _STEP_LABELS.get(method_name, method_name)

    def _metric(self, method_name: str) -> str | None:
        """Kennzahl des abgeschlossenen Schritts (aus Pipeline/CostTracker)."""
        if method_name == "sample":
            return f"{self._cost.probes} Probes"
        if method_name == "crawl_and_report":
            report = self._pipeline.report
            return f"{report.n_pages} Seiten" if report is not None else None
        if isinstance(self._pipeline, Sprint2Pipeline | Sprint3Pipeline | Sprint4Pipeline):
            if method_name == "mine_patterns" and self._pipeline.pattern_report is not None:
                return f"{len(self._pipeline.pattern_report.templates)} Templates"
            if method_name == "audit_flops" and self._pipeline.audit_report is not None:
                return f"{len(self._pipeline.audit_report.findings)} Findings"
        if isinstance(self._pipeline, Sprint3Pipeline | Sprint4Pipeline):
            if method_name == "propose_fixes" and self._pipeline.fix_plan is not None:
                return f"{len(self._pipeline.fix_plan.proposals)} Patches"
            if method_name == "await_approval" and self._pipeline.decisions is not None:
                n_ok = sum(1 for d in self._pipeline.decisions.values() if d.approved)
                return f"{n_ok} freigegeben"
            if method_name == "apply_patches" and self._pipeline.deploy_result is not None:
                return f"{len(self._pipeline.deploy_result.applied_patch_ids)} Deploy (Dry-Run)"
        if isinstance(self._pipeline, Sprint4Pipeline):
            if method_name == "retrieve_memory":
                return f"{len(self._pipeline.retrieved_memory)} Hypothesen"
            if method_name == "reprobe_and_learn" and self._pipeline.effect_report is not None:
                effect = self._pipeline.effect_report
                return f"{effect.n_improved}/{len(effect.hypotheses)} verbessert"
        return None

    def _step_started(self, method_name: str) -> None:
        if method_name in self._tasks:
            return
        self._started_at[method_name] = time.monotonic()
        description = f"[bold]{self._label(method_name)}[/]  [{GREY}]laeuft …[/]"
        self._tasks[method_name] = self._progress.add_task(description, total=1)

    def _step_finished(self, method_name: str) -> None:
        task_id = self._tasks.get(method_name)
        if task_id is None:
            return
        duration = time.monotonic() - self._started_at.get(method_name, time.monotonic())
        metric = self._metric(method_name)
        suffix = f"{metric} · {duration:.1f} s" if metric else f"{duration:.1f} s"
        self._progress.update(
            task_id,
            completed=1,
            description=f"[bold]{self._label(method_name)}[/]  [{GREY}]{suffix}[/]",
        )
