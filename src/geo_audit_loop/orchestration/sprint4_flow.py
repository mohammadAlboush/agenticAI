"""Sprint-4-Orchestrierung: der geschlossene Lern-Loop ueber dem Sprint-3-Fix-/Deploy-Loop.

Die framework-freie ``Sprint4Pipeline`` umschliesst die ``Sprint3Pipeline`` und schliesst den
Regelkreis: sie ruft VOR dem Fix das Gedaechtnis ab (``retrieve_memory`` -> beeinflusst den
naechsten Fix-Run, Projektregeln §8) und misst NACH dem (Dry-Run-)Deploy den Effekt
(``reprobe`` -> ``form_effect`` -> ``store``). ``Sprint4Flow`` ist der duenne CrewAI-``Flow``.

**HITL bleibt hart (Projektregeln §6):** Re-Probe/Lernen betrifft ausschliesslich freigegebene,
angewandte Patches; ohne Freigabe wird nichts gemessen und nichts gelernt.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel, PrivateAttr

from geo_audit_loop.agents.effect_analyst import EffectAnalystService
from geo_audit_loop.agents.sampler import SamplerService
from geo_audit_loop.config import constants as c
from geo_audit_loop.domain.audit import AuditReport
from geo_audit_loop.domain.effect import EffectHypothesis, EffectReport
from geo_audit_loop.domain.entity import EntityGraphReport
from geo_audit_loop.domain.findings import TopFlopReport
from geo_audit_loop.domain.fix import ApprovalDecision, DeployResult, FixPlan, FixProposal
from geo_audit_loop.domain.memory import MemoryQuery
from geo_audit_loop.domain.probe import ProbePrompt
from geo_audit_loop.domain.run import RunContext, RunStatus
from geo_audit_loop.domain.templates import PatternReport
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.orchestration.sprint3_flow import Sprint3Pipeline
from geo_audit_loop.ports.memory import MemoryPort

_AGENT = "orchestration"

#: Fabrik: baut aus den freigegebenen Ziel-URLs einen Re-Probe-Sampler (geboostete Engines).
ReprobeSamplerFactory = Callable[[frozenset[str]], SamplerService]


class Sprint4Pipeline:
    """Framework-freier geschlossener Loop: S3-Fix/Deploy + Gedaechtnis-Abruf + Effekt-Re-Probe."""

    def __init__(
        self,
        *,
        base: Sprint3Pipeline,
        memory: MemoryPort,
        effect_analyst: EffectAnalystService,
        build_reprobe_sampler: ReprobeSamplerFactory,
        prompts: Sequence[ProbePrompt],
        run_context: RunContext,
        logger: logging.Logger | None = None,
    ) -> None:
        self._base = base
        self._memory = memory
        self._effect_analyst = effect_analyst
        self._build_reprobe_sampler = build_reprobe_sampler
        self._prompts = prompts
        self._run_context = run_context
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._retrieved: tuple[EffectHypothesis, ...] = ()
        self._effect_report: EffectReport | None = None

    # --- an die Sprint-3-Basis delegierte Properties ------------------------
    @property
    def run_id(self) -> str:
        """Die run_id dieses Laufs."""
        return self._base.run_id

    @property
    def report(self) -> TopFlopReport | None:
        """Der Top/Flop-Report (Sprint-1-Messung)."""
        return self._base.report

    @property
    def entity_graph(self) -> EntityGraphReport | None:
        """Der Entity-/Knowledge-Graph-Report (Session 8, deterministisch)."""
        return self._base.entity_graph

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
        """Der Fix-Plan (Sprint 3)."""
        return self._base.fix_plan

    @property
    def decisions(self) -> dict[str, ApprovalDecision] | None:
        """Die HITL-Entscheidungen (Sprint 3)."""
        return self._base.decisions

    @property
    def deploy_result(self) -> DeployResult | None:
        """Das Deploy-Ergebnis (Sprint 3)."""
        return self._base.deploy_result

    @property
    def retrieved_memory(self) -> tuple[EffectHypothesis, ...]:
        """Die vor dem Fix abgerufenen Gedaechtnis-Hypothesen (Sprint 4)."""
        return self._retrieved

    @property
    def effect_report(self) -> EffectReport | None:
        """Der Effekt-Report des geschlossenen Loops (``None`` vor Ausfuehrung)."""
        return self._effect_report

    # --- Sprint-1/2/3-Schritte (Delegation) ---------------------------------
    def sample(self) -> None:
        """Schritt 1: Sampling (Baseline-Phase)."""
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

    # --- Sprint-4-Schritte --------------------------------------------------
    def retrieve_memory(self) -> tuple[EffectHypothesis, ...]:
        """Schritt 5: relevante Effekt-Hypothesen abrufen (beeinflusst den naechsten Fix, §8)."""
        query = MemoryQuery(target_domain=self._run_context.target_domain, top_k=c.MEMORY_TOP_K)
        self._retrieved = tuple(self._memory.retrieve(query))
        log_event(
            self._log,
            "memory.retrieve",
            run_id=self.run_id,
            agent=_AGENT,
            n_retrieved=len(self._retrieved),
        )
        return self._retrieved

    def propose_fixes(self) -> FixPlan:
        """Schritt 6: gedaechtnis-informierter Fix-Agent (abgerufene Hypothesen fliessen ein)."""
        return self._base.propose_fixes(self._retrieved)

    def await_approval(self) -> dict[str, ApprovalDecision]:
        """Schritt 7: Human-in-the-Loop-Gate (unveraendert hart, §6)."""
        return self._base.await_approval()

    def apply_patches(self) -> DeployResult:
        """Schritt 8: Deploy (sicherer Dry-Run); Finalisieren aufgeschoben bis nach dem Lernen."""
        return self._base.apply_patches(finalize=False)

    def _approved_proposals(self) -> list[FixProposal]:
        plan = self._base.fix_plan
        decisions = self._base.decisions
        if plan is None or decisions is None:
            return []
        return [
            p for p in plan.proposals if (d := decisions.get(p.patch_id)) is not None and d.approved
        ]

    def reprobe_and_learn(self) -> EffectReport:
        """Schritt 9-11: Effekt re-proben, Hypothesen bilden + speichern, Run finalisieren.

        Nur freigegebene, angewandte Patches werden re-geprobt (HITL bleibt hart, §6). Ohne
        Freigabe bleibt der Effekt-Report leer (ehrlicher Null-Effekt). Danach wird der Run als
        COMPLETED abgeschlossen (die persistierten Kosten enthalten jetzt auch die Re-Probe).
        """
        approved = self._approved_proposals()
        approved_urls = frozenset(p.target_url for p in approved)
        if approved_urls:
            reprobe_sampler = self._build_reprobe_sampler(approved_urls)
            reprobe_sampler.run(self._run_context, self._prompts)
        plan = self._base.fix_plan
        prompt_version = plan.prompt_version if plan is not None else c.FIX_AGENT_LEARN_VERSION
        self._effect_report = self._effect_analyst.run(self._run_context, approved, prompt_version)
        self._base.finalize_completed()
        return self._effect_report

    def run(self) -> TopFlopReport:
        """Fuehrt den gesamten geschlossenen Loop aus (framework-freier Komplettlauf)."""
        self.sample()
        report = self.crawl_and_report()
        self.mine_patterns()
        self.audit_flops()
        self.retrieve_memory()
        self.propose_fixes()
        self.await_approval()
        self.apply_patches()
        self.reprobe_and_learn()
        return report


class Sprint4State(BaseModel):
    """Typisierter Flow-Zustand des geschlossenen Lern-Loops."""

    run_id: str = ""
    status: str = ""
    n_pages: int = 0
    n_probes: int = 0
    n_templates: int = 0
    n_findings: int = 0
    n_proposals: int = 0
    n_approved: int = 0
    n_retrieved: int = 0
    n_hypotheses: int = 0
    n_improved: int = 0
    mean_delta: float = 0.0
    deploy_status: str = ""


class Sprint4Flow(Flow[Sprint4State]):
    """Duenner CrewAI-``Flow``, der die ``Sprint4Pipeline`` Schritt fuer Schritt ausfuehrt."""

    _pipeline: Sprint4Pipeline = PrivateAttr()

    def __init__(self, pipeline: Sprint4Pipeline) -> None:
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
    def retrieve_memory(self) -> str:
        """Flow-Schritt 5: Gedaechtnis-Abruf (beeinflusst den Fix-Run)."""
        self.state.n_retrieved = len(self._pipeline.retrieve_memory())
        return "retrieved"

    @listen(retrieve_memory)
    def propose_fixes(self) -> str:
        """Flow-Schritt 6: gedaechtnis-informierter Fix-Agent."""
        plan = self._pipeline.propose_fixes()
        self.state.n_proposals = len(plan.proposals)
        return "proposed"

    @listen(propose_fixes)
    def await_approval(self) -> str:
        """Flow-Schritt 7: Human-in-the-Loop-Gate."""
        decisions = self._pipeline.await_approval()
        self.state.n_approved = sum(1 for d in decisions.values() if d.approved)
        return "approved"

    @listen(await_approval)
    def apply_patches(self) -> str:
        """Flow-Schritt 8: Deploy (sicherer Dry-Run)."""
        result = self._pipeline.apply_patches()
        self.state.deploy_status = result.status.value
        return "deployed"

    @listen(apply_patches)
    def reprobe_and_learn(self) -> str:
        """Flow-Schritt 9-11: Effekt re-proben, Hypothesen speichern, Run abschliessen."""
        effect = self._pipeline.reprobe_and_learn()
        self.state.n_hypotheses = len(effect.hypotheses)
        self.state.n_improved = effect.n_improved
        self.state.mean_delta = effect.mean_delta
        self.state.status = RunStatus.COMPLETED.value
        return "learned"
