"""Phase-2-Gate: Minimal-Stubs erfuellen die Port-Protokolle (strukturell + Laufzeit).

Die typisierten Zuweisungen (``x: SomePort = Stub()``) zwingen mypy zur strukturellen
Pruefung; ``isinstance`` prueft zusaetzlich zur Laufzeit (runtime_checkable).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from geo_audit_loop.domain.audit import AuditReport
from geo_audit_loop.domain.competitive import ShareOfVoiceReport
from geo_audit_loop.domain.coverage import CoverageReport
from geo_audit_loop.domain.effect import EffectHypothesis, EffectReport
from geo_audit_loop.domain.findings import TopFlopReport
from geo_audit_loop.domain.fix import ApprovalDecision, DeployResult, FixPlan
from geo_audit_loop.domain.inventory import CrawlOptions, PageInventory
from geo_audit_loop.domain.memory import MemoryQuery
from geo_audit_loop.domain.probe import EngineId, ProbePhase, ProbeRequest, ProbeResult
from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningResult
from geo_audit_loop.domain.run import RunContext, RunRecord
from geo_audit_loop.domain.templates import PatternReport
from geo_audit_loop.ports.crawl import CrawlPort
from geo_audit_loop.ports.engine import EnginePort
from geo_audit_loop.ports.memory import MemoryPort
from geo_audit_loop.ports.proxy import ProxyPort
from geo_audit_loop.ports.publisher import PublisherPort
from geo_audit_loop.ports.reasoning import ReasoningPort
from geo_audit_loop.ports.storage import StoragePort

FIXED = datetime(2026, 1, 1, 12, 0, 0)


class _StubEngine:
    engine_id = EngineId.PERPLEXITY

    def probe(self, request: ProbeRequest) -> ProbeResult:
        return ProbeResult(
            run_id=request.run_id,
            engine_id=request.engine_id,
            model=request.model,
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            probed_at=FIXED,
        )


class _StubProxy:
    @property
    def size(self) -> int:
        return 0

    def get(self, index: int) -> str | None:
        return None

    def label_for(self, index: int) -> str:
        return f"proxy-{index}"


class _StubCrawl:
    def crawl(self, domain: str, options: CrawlOptions) -> list[PageInventory]:
        return []


class _StubStorage:
    def initialize(self) -> None: ...

    def save_run(self, run: RunRecord) -> None: ...

    def update_run(self, run: RunRecord) -> None: ...

    def load_run(self, run_id: str) -> RunRecord | None:
        return None

    def list_runs(self) -> list[RunRecord]:
        return []

    def delete_run(self, run_id: str) -> None: ...

    def save_probe(self, result: ProbeResult) -> None: ...

    def has_probe(
        self,
        run_id: str,
        prompt_id: str,
        engine_id: EngineId,
        proxy_label: str | None,
        phase: ProbePhase = ProbePhase.BASELINE,
    ) -> bool:
        return False

    def load_probes(self, run_id: str, phase: ProbePhase | None = None) -> list[ProbeResult]:
        return []

    def save_pages(self, run_id: str, pages: list[PageInventory]) -> None: ...

    def load_pages(self, run_id: str) -> list[PageInventory]:
        return []

    def save_report(self, report: TopFlopReport) -> None: ...

    def load_report(self, run_id: str) -> TopFlopReport | None:
        return None

    def save_pattern_report(self, report: PatternReport) -> None: ...

    def load_pattern_report(self, run_id: str) -> PatternReport | None:
        return None

    def save_audit_report(self, report: AuditReport) -> None: ...

    def load_audit_report(self, run_id: str) -> AuditReport | None:
        return None

    def append_reasoning_log(
        self, run_id: str, task: str, model: str, prompt_version: str, raw_text: str
    ) -> None: ...

    def save_fix_plan(self, plan: FixPlan) -> None: ...

    def load_fix_plan(self, run_id: str) -> FixPlan | None:
        return None

    def save_decision(self, decision: ApprovalDecision) -> None: ...

    def save_approvals(self, run_id: str, decisions: Sequence[ApprovalDecision]) -> None: ...

    def load_approvals(self, run_id: str) -> list[ApprovalDecision]:
        return []

    def save_deploy_result(self, result: DeployResult) -> None: ...

    def load_deploy_result(self, run_id: str) -> DeployResult | None:
        return None

    def save_effect_report(self, report: EffectReport) -> None: ...

    def load_effect_report(self, run_id: str) -> EffectReport | None:
        return None

    def save_sov_report(self, report: ShareOfVoiceReport) -> None: ...

    def load_sov_report(self, run_id: str) -> ShareOfVoiceReport | None:
        return None

    def save_coverage_report(self, report: CoverageReport) -> None: ...

    def load_coverage_report(self, run_id: str) -> CoverageReport | None:
        return None


class _StubMemory:
    def store(self, hypothesis: EffectHypothesis) -> None: ...

    def retrieve(self, context: MemoryQuery) -> list[EffectHypothesis]:
        return []


class _StubPublisher:
    name = "stub"

    def publish(
        self,
        plan: FixPlan,
        decisions: Mapping[str, ApprovalDecision],
        *,
        run_context: RunContext,
        dry_run: bool = True,
    ) -> DeployResult:
        return DeployResult(
            run_id=plan.run_id,
            target_domain=plan.target_domain,
            generated_at=FIXED,
            publisher=self.name,
        )


def test_engine_port_conformance() -> None:
    engine: EnginePort = _StubEngine()
    assert isinstance(engine, EnginePort)


def test_proxy_port_conformance() -> None:
    proxy: ProxyPort = _StubProxy()
    assert isinstance(proxy, ProxyPort)
    assert proxy.label_for(3) == "proxy-3"


def test_crawl_port_conformance() -> None:
    crawler: CrawlPort = _StubCrawl()
    assert isinstance(crawler, CrawlPort)


class _StubReasoning:
    model = "stub-model"

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        return ReasoningResult(
            run_id=request.run_id, task=request.task, model=request.model, generated_at=FIXED
        )


def test_storage_port_conformance() -> None:
    storage: StoragePort = _StubStorage()
    assert isinstance(storage, StoragePort)
    assert storage.load_run("x") is None


def test_reasoning_port_conformance() -> None:
    reasoning: ReasoningPort = _StubReasoning()
    assert isinstance(reasoning, ReasoningPort)
    assert reasoning.model == "stub-model"


def test_publisher_port_conformance() -> None:
    publisher: PublisherPort = _StubPublisher()
    assert isinstance(publisher, PublisherPort)
    assert publisher.name == "stub"


def test_memory_port_conformance() -> None:
    memory: MemoryPort = _StubMemory()
    assert isinstance(memory, MemoryPort)
    assert memory.retrieve(MemoryQuery(target_domain="it-sicherheit.de")) == []
