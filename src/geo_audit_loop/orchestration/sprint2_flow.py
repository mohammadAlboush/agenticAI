"""Sprint-2-Orchestrierung: der Lern-Loop ueber der Sprint-1-Mess-Schicht.

Die framework-freie ``Sprint2Pipeline`` umschliesst die ``Sprint1Pipeline`` (Sampler ->
Crawler -> Top/Flop) und ergaenzt zwei Lern-Schritte: ``mine_patterns`` (Pattern-Miner)
und ``audit_flops`` (GEO-Auditor). ``Sprint2Flow`` ist der duenne CrewAI-``Flow`` am Rand,
der die vier Schritte als ``@start``/``@listen`` ausfuehrt.
"""

from __future__ import annotations

import logging

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel, PrivateAttr

from geo_audit_loop.agents.geo_auditor import GeoAuditorService
from geo_audit_loop.agents.pattern_miner import PatternMinerService
from geo_audit_loop.domain.audit import AuditReport
from geo_audit_loop.domain.errors import GeoAuditError
from geo_audit_loop.domain.findings import TopFlopReport
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.run import RunContext, RunStatus
from geo_audit_loop.domain.templates import PatternReport
from geo_audit_loop.orchestration.sprint1_flow import Sprint1Pipeline
from geo_audit_loop.ports.storage import StoragePort

_AGENT = "orchestration"


class Sprint2Pipeline:
    """Framework-freier Lern-Loop: S1-Messung + Pattern-Miner + GEO-Auditor."""

    def __init__(
        self,
        *,
        base: Sprint1Pipeline,
        pattern_miner: PatternMinerService,
        geo_auditor: GeoAuditorService,
        storage: StoragePort,
        run_context: RunContext,
        logger: logging.Logger | None = None,
    ) -> None:
        self._base = base
        self._pattern_miner = pattern_miner
        self._geo_auditor = geo_auditor
        self._storage = storage
        self._run_context = run_context
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._pages: tuple[PageInventory, ...] | None = None
        self._pattern_report: PatternReport | None = None
        self._audit_report: AuditReport | None = None

    @property
    def run_id(self) -> str:
        """Die run_id dieses Laufs."""
        return self._base.run_id

    @property
    def report(self) -> TopFlopReport | None:
        """Der Top/Flop-Report aus Schritt 2 (Sprint-1-Messung)."""
        return self._base.report

    @property
    def pattern_report(self) -> PatternReport | None:
        """Die geminten Templates aus Schritt 3 (``None`` vor Ausfuehrung)."""
        return self._pattern_report

    @property
    def audit_report(self) -> AuditReport | None:
        """Die priorisierten Findings aus Schritt 4 (``None`` vor Ausfuehrung)."""
        return self._audit_report

    def sample(self) -> None:
        """Schritt 1: Probe-Matrix ausfuehren (delegiert an die S1-Pipeline)."""
        self._base.sample()

    def crawl_and_report(self) -> TopFlopReport:
        """Schritt 2: Inventar crawlen und Top/Flop-Report bauen (S1-Pipeline)."""
        return self._base.crawl_and_report()

    def _require_report(self) -> TopFlopReport:
        report = self._base.report
        if report is None:
            raise GeoAuditError("Top/Flop-Report fehlt - sample/crawl zuerst ausfuehren")
        return report

    def _load_pages(self) -> tuple[PageInventory, ...]:
        if self._pages is None:
            self._pages = tuple(self._storage.load_pages(self._run_context.run_id))
        return self._pages

    def mine_patterns(self) -> PatternReport:
        """Schritt 3: aus den Top-Seiten Best-Practice-Templates minen."""
        self._pattern_report = self._pattern_miner.run(
            self._run_context, self._require_report(), self._load_pages()
        )
        return self._pattern_report

    def audit_flops(self) -> AuditReport:
        """Schritt 4: Flop-Seiten gegen die Templates auditieren (priorisierte Findings)."""
        if self._pattern_report is None:
            self.mine_patterns()
        assert self._pattern_report is not None
        self._audit_report = self._geo_auditor.run(
            self._run_context, self._require_report(), self._load_pages(), self._pattern_report
        )
        return self._audit_report

    def run(self) -> TopFlopReport:
        """Fuehrt alle vier Schritte aus (framework-freier Komplettlauf)."""
        self.sample()
        report = self.crawl_and_report()
        self.mine_patterns()
        self.audit_flops()
        return report


class Sprint2State(BaseModel):
    """Typisierter Flow-Zustand des Lern-Loops."""

    run_id: str = ""
    status: str = ""
    n_pages: int = 0
    n_probes: int = 0
    n_templates: int = 0
    n_findings: int = 0


class Sprint2Flow(Flow[Sprint2State]):
    """Duenner CrewAI-``Flow``, der die ``Sprint2Pipeline`` Schritt fuer Schritt ausfuehrt."""

    _pipeline: Sprint2Pipeline = PrivateAttr()

    def __init__(self, pipeline: Sprint2Pipeline) -> None:
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
        self.state.status = RunStatus.COMPLETED.value
        return "done"
