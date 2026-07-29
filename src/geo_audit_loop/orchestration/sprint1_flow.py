"""Sprint-1-Orchestrierung.

Die eigentliche Pipeline-Logik liegt in der framework-freien, voll testbaren
``Sprint1Pipeline`` (Kern kennt CrewAI nicht). ``Sprint1Flow`` ist ein duenner
CrewAI-``Flow`` am Rand, der die Pipeline-Schritte als ``@start``/``@listen`` ausfuehrt
und so den geschlossenen Loop in CrewAI abbildet (Erweiterung in spaeteren Sprints).

Hinweis: CrewAI-Telemetrie wird per Env (CLI/conftest) abgeschaltet, bevor crewai laedt.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel, PrivateAttr

from geo_audit_loop.agents.inventory_crawler import InventoryCrawlerService
from geo_audit_loop.agents.sampler import SamplerService
from geo_audit_loop.agents.serp_sampler import SerpSamplerService
from geo_audit_loop.domain.errors import BudgetExceeded
from geo_audit_loop.domain.findings import TopFlopReport
from geo_audit_loop.domain.inventory import CrawlOptions
from geo_audit_loop.domain.metrics import ProbeAggregate
from geo_audit_loop.domain.overlap import OverlapReport, compute_overlap
from geo_audit_loop.domain.probe import ProbePhase, ProbePrompt
from geo_audit_loop.domain.run import RunContext, RunRecord, RunStatus
from geo_audit_loop.domain.serp import SerpQuery, SerpResult
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.ports.storage import StoragePort

_AGENT = "orchestration"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Sprint1Pipeline:
    """Framework-freie Orchestrierung: Sampler -> Crawler -> Report mit Run-Lifecycle."""

    def __init__(
        self,
        *,
        sampler: SamplerService,
        crawler: InventoryCrawlerService,
        storage: StoragePort,
        cost_tracker: CostTracker,
        run_context: RunContext,
        prompts: Sequence[ProbePrompt],
        options: CrawlOptions,
        top_n: int,
        serp_sampler: SerpSamplerService | None = None,
        serp_queries: Sequence[SerpQuery] = (),
        serp_query_set_version: str = "",
        logger: logging.Logger | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sampler = sampler
        self._crawler = crawler
        self._storage = storage
        self._cost = cost_tracker
        self._run_context = run_context
        self._prompts = prompts
        self._options = options
        self._top_n = top_n
        # Live-Loop (optional): SERP-Messung parallel zur Baseline; None = exakter No-Op.
        self._serp_sampler = serp_sampler
        self._serp_queries = serp_queries
        self._serp_query_set_version = serp_query_set_version
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._clock = clock if clock is not None else _utc_now
        self._aggregates: list[ProbeAggregate] = []
        self._report: TopFlopReport | None = None
        self._serp_results: list[SerpResult] = []
        self._overlap_report: OverlapReport | None = None

    @property
    def run_id(self) -> str:
        """Die run_id dieses Laufs."""
        return self._run_context.run_id

    @property
    def report(self) -> TopFlopReport | None:
        """Der erzeugte Top/Flop-Report (nach ``run``); ``None`` bei Abbruch."""
        return self._report

    @property
    def overlap_report(self) -> OverlapReport | None:
        """Der SERP-Overlap-Report (Live-Loop); ``None`` ohne SERP-Provider."""
        return self._overlap_report

    def sample(self) -> None:
        """Schritt 1: Run anlegen und die Probe-Matrix ausfuehren (budget-bewacht).

        Mit verdrahtetem SERP-Sampler laeuft parallel zur Baseline die Google-Top-K-
        Messung (checkpoint-faehig, eigene Provider-Quote); ohne bleibt der Schritt
        byte-identisch zum bisherigen Verhalten.
        """
        self._storage.save_run(self._record(RunStatus.RUNNING, finished=False))
        log_event(self._log, "run.start", run_id=self.run_id, agent=_AGENT)
        try:
            self._aggregates = self._sampler.run(self._run_context, self._prompts)
        except BudgetExceeded as exc:
            self._finalize(RunStatus.ABORTED, str(exc))
            raise
        if self._serp_sampler is not None:
            self._serp_results = self._serp_sampler.run(self._run_context, self._serp_queries)

    def crawl_and_report(self, *, finalize: bool = True) -> TopFlopReport:
        """Schritt 2: Inventar crawlen, Top/Flop bauen, Run abschliessen.

        ``finalize=False`` schiebt den COMPLETED-Abschluss auf (Sprint 2 finalisiert erst
        nach den Lern-Schritten, damit die persistierten Kosten das Reasoning enthalten).
        Mit verdrahtetem SERP-Sampler wird zusaetzlich der Overlap-Report (Google-Top-K
        vs. AI-Zitate) berechnet und persistiert.
        """
        report = self._crawler.run(
            self._run_context, self._options, aggregates=self._aggregates, top_n=self._top_n
        )
        self._report = report
        if self._serp_sampler is not None:
            self._overlap_report = compute_overlap(
                run_id=self._run_context.run_id,
                target_domain=self._run_context.target_domain,
                provider=self._serp_sampler.provider,
                query_set_version=self._serp_query_set_version,
                serp_results=self._serp_results,
                probes=self._storage.load_probes(self._run_context.run_id, ProbePhase.BASELINE),
                generated_at=self._clock(),
            )
            self._storage.save_overlap_report(self._overlap_report)
            log_event(
                self._log,
                "overlap.done",
                run_id=self.run_id,
                agent=_AGENT,
                n_queries=self._overlap_report.n_queries,
                mean_jaccard=self._overlap_report.mean_jaccard,
            )
        if finalize:
            self._finalize(RunStatus.COMPLETED, None)
        return report

    def finalize_completed(self) -> None:
        """Schliesst den Run als COMPLETED ab (fuer aufgeschobenes Finalisieren in Sprint 2)."""
        self._finalize(RunStatus.COMPLETED, None)

    def run(self) -> TopFlopReport:
        """Fuehrt beide Schritte aus (framework-freier Komplettlauf)."""
        self.sample()
        return self.crawl_and_report()

    def _finalize(self, status: RunStatus, error: str | None) -> None:
        snapshot = self._cost.snapshot()
        self._storage.update_run(self._record(status, finished=True, error=error))
        log_event(
            self._log,
            "run.finish",
            run_id=self.run_id,
            agent=_AGENT,
            status=status.value,
            probes=snapshot.probes,
            total_usd=snapshot.total_usd,
        )

    def _record(self, status: RunStatus, *, finished: bool, error: str | None = None) -> RunRecord:
        snapshot = self._cost.snapshot()
        return RunRecord(
            run_id=self._run_context.run_id,
            target_domain=self._run_context.target_domain,
            status=status,
            started_at=self._run_context.started_at,
            finished_at=self._clock() if finished else None,
            seed=self._run_context.seed,
            prompt_set_version=self._run_context.prompt_set_version,
            config_hash=self._run_context.config_hash,
            live_engines=self._run_context.live_engines,
            total_probes=snapshot.probes,
            total_tokens=snapshot.total_tokens,
            total_cost_usd=snapshot.total_usd,
            error=error,
        )


class Sprint1State(BaseModel):
    """Typisierter Flow-Zustand (sichtbarer Fortschritt des Runs)."""

    run_id: str = ""
    status: str = ""
    n_pages: int = 0
    n_probes: int = 0


class Sprint1Flow(Flow[Sprint1State]):
    """Duenner CrewAI-``Flow``, der die ``Sprint1Pipeline`` Schritt fuer Schritt ausfuehrt."""

    _pipeline: Sprint1Pipeline = PrivateAttr()

    def __init__(self, pipeline: Sprint1Pipeline) -> None:
        super().__init__()
        # Hinweis: KEINE oeffentliche Property hier - CrewAIs Flow-Init scannt oeffentliche
        # Attribute via getattr; den Report holt man ueber die Pipeline (gleiche Instanz).
        self._pipeline = pipeline

    @start()
    def sample(self) -> str:
        """Flow-Schritt 1: Sampling."""
        self._pipeline.sample()
        self.state.run_id = self._pipeline.run_id
        return "sampled"

    @listen(sample)
    def crawl_and_report(self) -> str:
        """Flow-Schritt 2: Crawl + Report."""
        report = self._pipeline.crawl_and_report()
        self.state.status = RunStatus.COMPLETED.value
        self.state.n_pages = report.n_pages
        self.state.n_probes = report.n_probes
        return "done"
