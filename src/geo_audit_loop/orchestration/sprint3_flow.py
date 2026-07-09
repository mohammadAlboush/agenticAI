"""Sprint-3-Orchestrierung: der Fix-/Deploy-Loop ueber dem Sprint-2-Lern-Loop.

Die framework-freie ``Sprint3Pipeline`` umschliesst die ``Sprint2Pipeline`` (Messung +
Pattern-Miner + GEO-Auditor) und ergaenzt drei Schritte: ``propose_fixes`` (Fix-Agent ->
``FixPlan``), ``await_approval`` (Human-in-the-Loop-Gate -> ``ApprovalDecision``s) und
``apply_patches`` (Publisher -> ``DeployResult``, sicherer Dry-Run). ``Sprint3Flow`` ist der
duenne CrewAI-``Flow`` am Rand, der die sieben Schritte als ``@start``/``@listen`` ausfuehrt.

**Hartes HITL-Gate (Projektregeln §6):** ``apply_patches`` ohne vorheriges ``await_approval``
wirft ``DeployBlocked`` — aus einem ``FixPlan`` wird NIE direkt ein ``DeployResult``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel, PrivateAttr

from geo_audit_loop.agents.fix_agent import FixAgentService
from geo_audit_loop.domain.audit import AuditReport
from geo_audit_loop.domain.effect import EffectHypothesis
from geo_audit_loop.domain.errors import DeployBlocked, GeoAuditError
from geo_audit_loop.domain.findings import TopFlopReport
from geo_audit_loop.domain.fix import ApprovalDecision, DeployResult, FixPlan
from geo_audit_loop.domain.indexing import IndexSubmissionResult, build_index_submission
from geo_audit_loop.domain.overlap import OverlapReport
from geo_audit_loop.domain.run import RunContext, RunStatus
from geo_audit_loop.domain.templates import PatternReport
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.orchestration.approval import ApprovalGate
from geo_audit_loop.orchestration.sprint2_flow import Sprint2Pipeline
from geo_audit_loop.ports.indexing import IndexingPort
from geo_audit_loop.ports.publisher import PublisherPort
from geo_audit_loop.ports.storage import StoragePort

_AGENT = "orchestration"


class Sprint3Pipeline:
    """Framework-freier Fix-/Deploy-Loop: S2-Lernen + Fix-Agent + HITL-Gate + Deploy."""

    def __init__(
        self,
        *,
        base: Sprint2Pipeline,
        fix_agent: FixAgentService,
        publisher: PublisherPort,
        approval_gate: ApprovalGate,
        storage: StoragePort,
        run_context: RunContext,
        indexer: IndexingPort | None = None,
        deploy_dry_run: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self._base = base
        self._fix_agent = fix_agent
        self._publisher = publisher
        self._approval_gate = approval_gate
        self._storage = storage
        self._run_context = run_context
        # Live-Loop: Index-Kanal (None = kein Post-Deploy-Schritt) und Dry-Run-Steuerung.
        # deploy_dry_run=False setzt NUR die Factory (Doppel-Gate GEO_ALLOW_REMOTE + CLI).
        self._indexer = indexer
        self._deploy_dry_run = deploy_dry_run
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._fix_plan: FixPlan | None = None
        self._decisions: dict[str, ApprovalDecision] | None = None
        self._deploy_result: DeployResult | None = None
        self._index_result: IndexSubmissionResult | None = None

    # --- an die Sprint-2-Basis delegierte Properties ------------------------
    @property
    def run_id(self) -> str:
        """Die run_id dieses Laufs."""
        return self._base.run_id

    @property
    def report(self) -> TopFlopReport | None:
        """Der Top/Flop-Report (Sprint-1-Messung)."""
        return self._base.report

    @property
    def overlap_report(self) -> OverlapReport | None:
        """Der SERP-Overlap-Report (Live-Loop, delegiert)."""
        return self._base.overlap_report

    @property
    def pattern_report(self) -> PatternReport | None:
        """Die geminten Templates (Sprint 2)."""
        return self._base.pattern_report

    @property
    def audit_report(self) -> AuditReport | None:
        """Die priorisierten Findings (Sprint 2)."""
        return self._base.audit_report

    @property
    def fix_plan(self) -> FixPlan | None:
        """Der Fix-Plan aus Schritt 5 (``None`` vor Ausfuehrung)."""
        return self._fix_plan

    @property
    def decisions(self) -> dict[str, ApprovalDecision] | None:
        """Die HITL-Entscheidungen aus Schritt 6 (``None`` vor Ausfuehrung)."""
        return self._decisions

    @property
    def deploy_result(self) -> DeployResult | None:
        """Das Deploy-Ergebnis aus Schritt 7 (``None`` vor Ausfuehrung)."""
        return self._deploy_result

    @property
    def index_result(self) -> IndexSubmissionResult | None:
        """Das Index-Einreichungs-Ergebnis nach dem Deploy (``None`` ohne echten Apply)."""
        return self._index_result

    def finalize_completed(self) -> None:
        """Schliesst den Run als COMPLETED ab (delegiert; Sprint 4 finalisiert spaeter)."""
        self._base.finalize_completed()

    # --- Sprint-1/2-Schritte (Delegation) -----------------------------------
    def sample(self) -> None:
        """Schritt 1: Sampling."""
        self._base.sample()

    def crawl_and_report(self) -> TopFlopReport:
        """Schritt 2: Crawl + Top/Flop-Report."""
        return self._base.crawl_and_report()

    def mine_patterns(self) -> PatternReport:
        """Schritt 3: Pattern-Miner."""
        return self._base.mine_patterns()

    def audit_flops(self) -> AuditReport:
        """Schritt 4: GEO-Auditor."""
        return self._base.audit_flops()

    # --- Sprint-3-Schritte --------------------------------------------------
    def propose_fixes(self, memory_hypotheses: Sequence[EffectHypothesis] = ()) -> FixPlan:
        """Schritt 5: aus den Findings konkrete Patches ableiten (+ persistieren).

        ``memory_hypotheses`` (Sprint 4) reicht der Fix-Agent an sein Lern-Signal weiter;
        leer => unveraendertes Sprint-3-Verhalten.
        """
        if self._base.audit_report is None:
            self.audit_flops()
        audit = self._base.audit_report
        patterns = self._base.pattern_report
        if audit is None or patterns is None:
            raise GeoAuditError("Audit/Pattern fehlt - audit_flops zuerst ausfuehren")
        self._fix_plan = self._fix_agent.run(
            self._run_context, audit, patterns, self._base.load_pages(), memory_hypotheses
        )
        self._storage.save_fix_plan(self._fix_plan)
        return self._fix_plan

    def await_approval(self) -> dict[str, ApprovalDecision]:
        """Schritt 6: Human-in-the-Loop-Gate -> Freigabe/Ablehnung je Patch (+ persistieren)."""
        if self._fix_plan is None:
            self.propose_fixes()
        assert self._fix_plan is not None
        self._decisions = self._approval_gate.decide(self._fix_plan, self._run_context)
        self._storage.save_approvals(self._run_context.run_id, tuple(self._decisions.values()))
        return self._decisions

    def apply_patches(self, *, finalize: bool = True) -> DeployResult:
        """Schritt 7: freigegebene Patches deployen (sicherer Dry-Run) + Run finalisieren.

        Hartes Gate (Projektregeln §6): ohne vorherige ``await_approval`` -> ``DeployBlocked``.
        ``finalize=False`` schiebt den COMPLETED-Abschluss auf (Sprint 4 finalisiert erst nach
        Re-Probe + Gedaechtnis-Schreiben, damit die persistierten Kosten alles enthalten).
        """
        if self._decisions is None:
            raise DeployBlocked("HITL-Freigabe fehlt - await_approval zuerst ausfuehren")
        assert self._fix_plan is not None
        self._deploy_result = self._publisher.publish(
            self._fix_plan,
            self._decisions,
            run_context=self._run_context,
            dry_run=self._deploy_dry_run,
        )
        self._storage.save_deploy_result(self._deploy_result)
        self._notify_index()
        if finalize:
            self._base.finalize_completed()  # Kosten enthalten jetzt das Fix-Reasoning
        return self._deploy_result

    def _notify_index(self) -> None:
        """Post-Deploy: geaenderte URLs beim Such-Index einreichen (Live-Loop, best effort).

        ``build_index_submission`` ist das harte Gate: nur ein echter ``APPLIED``-Deploy
        ohne Dry-Run liefert eine Submission — offline/dry-run wird der ``IndexingPort``
        strukturell NIE aufgerufen. Fehler beim Einreichen werden geloggt, killen aber
        nie den Run (der Deploy ist bereits persistiert).
        """
        if self._indexer is None or self._fix_plan is None or self._deploy_result is None:
            return
        submission = build_index_submission(self._fix_plan, self._deploy_result)
        if submission is None:
            return
        try:
            self._index_result = self._indexer.submit(submission, run_context=self._run_context)
            self._storage.save_index_submission(self._index_result)
        except GeoAuditError as exc:
            log_event(
                self._log,
                "index_submission.failed",
                run_id=self.run_id,
                level=logging.WARNING,
                agent=_AGENT,
                adapter=self._indexer.name,
                error=str(exc),
            )
            return
        log_event(
            self._log,
            "index_submission.done",
            run_id=self.run_id,
            agent=_AGENT,
            adapter=self._indexer.name,
            status=self._index_result.status.value,
            n_urls=len(self._index_result.urls),
        )

    def run(self) -> TopFlopReport:
        """Fuehrt alle sieben Schritte aus (framework-freier Komplettlauf)."""
        self.sample()
        report = self.crawl_and_report()
        self.mine_patterns()
        self.audit_flops()
        self.propose_fixes()
        self.await_approval()
        self.apply_patches()
        return report


class Sprint3State(BaseModel):
    """Typisierter Flow-Zustand des Fix-/Deploy-Loops."""

    run_id: str = ""
    status: str = ""
    n_pages: int = 0
    n_probes: int = 0
    n_templates: int = 0
    n_findings: int = 0
    n_proposals: int = 0
    n_approved: int = 0
    deploy_status: str = ""
    dry_run: bool = True


class Sprint3Flow(Flow[Sprint3State]):
    """Duenner CrewAI-``Flow``, der die ``Sprint3Pipeline`` Schritt fuer Schritt ausfuehrt."""

    _pipeline: Sprint3Pipeline = PrivateAttr()

    def __init__(self, pipeline: Sprint3Pipeline) -> None:
        super().__init__()
        self._pipeline = pipeline

    @start()
    def sample(self) -> str:
        """Flow-Schritt 1: Sampling."""
        self._pipeline.sample()
        self.state.run_id = self._pipeline.run_id
        return "sampled"

    @listen(sample)
    def crawl_and_report(self) -> str:
        """Flow-Schritt 2: Crawl + Top/Flop-Report."""
        report = self._pipeline.crawl_and_report()
        self.state.n_pages = report.n_pages
        self.state.n_probes = report.n_probes
        return "reported"

    @listen(crawl_and_report)
    def mine_patterns(self) -> str:
        """Flow-Schritt 3: Pattern-Miner."""
        patterns = self._pipeline.mine_patterns()
        self.state.n_templates = len(patterns.templates)
        return "mined"

    @listen(mine_patterns)
    def audit_flops(self) -> str:
        """Flow-Schritt 4: GEO-Auditor."""
        audit = self._pipeline.audit_flops()
        self.state.n_findings = len(audit.findings)
        return "audited"

    @listen(audit_flops)
    def propose_fixes(self) -> str:
        """Flow-Schritt 5: Fix-Agent."""
        plan = self._pipeline.propose_fixes()
        self.state.n_proposals = len(plan.proposals)
        return "proposed"

    @listen(propose_fixes)
    def await_approval(self) -> str:
        """Flow-Schritt 6: Human-in-the-Loop-Gate."""
        decisions = self._pipeline.await_approval()
        self.state.n_approved = sum(1 for d in decisions.values() if d.approved)
        return "approved"

    @listen(await_approval)
    def apply_patches(self) -> str:
        """Flow-Schritt 7: Deploy (sicherer Dry-Run)."""
        result = self._pipeline.apply_patches()
        self.state.deploy_status = result.status.value
        self.state.dry_run = result.dry_run
        self.state.status = RunStatus.COMPLETED.value
        return "deployed"
