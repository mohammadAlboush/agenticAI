"""Unit: Fix-Agent mit deterministischem Mock-Reasoning (kein Netz)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

import pytest

from geo_audit_loop.adapters.reasoning.mock import MockReasoningAdapter
from geo_audit_loop.adapters.sample_data import build_sample_inventory
from geo_audit_loop.agents.fix_agent import FixAgentService
from geo_audit_loop.agents.geo_auditor import GeoAuditorService
from geo_audit_loop.agents.pattern_miner import PatternMinerService
from geo_audit_loop.config.pricing import PRICE_TABLE
from geo_audit_loop.domain.audit import AuditReport
from geo_audit_loop.domain.errors import ReasoningError
from geo_audit_loop.domain.findings import TopFlopEntry, TopFlopReport
from geo_audit_loop.domain.geo import pyramid_rank
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.reasoning import (
    ReasoningRequest,
    ReasoningResult,
    ReasoningStatus,
    ReasoningUsage,
)
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.domain.templates import PatternReport
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.prompts.loader import load_prompt

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _ctx() -> RunContext:
    return RunContext(
        run_id="t",
        target_domain="it-sicherheit.de",
        started_at=FIXED,
        seed=42,
        prompt_set_version="v1",
        config_hash="hash",
    )


def _cost() -> CostTracker:
    return CostTracker(
        max_probes=1000, max_usd=10.0, max_tokens=10_000_000, price_table=PRICE_TABLE
    )


def _report(pages: Sequence[PageInventory]) -> TopFlopReport:
    urls = [p.page.url for p in pages]
    top = tuple(
        TopFlopEntry(position=i + 1, url=u, citation_count=70 - i, citation_rate=0.3 - 0.02 * i)
        for i, u in enumerate(urls[:3])
    )
    flop = tuple(
        TopFlopEntry(position=i + 1, url=u, citation_count=i + 1, citation_rate=0.01 * (i + 1))
        for i, u in enumerate(urls[-3:])
    )
    return TopFlopReport(
        run_id="t",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        n_probes=240,
        n_pages=len(pages),
        top=top,
        flop=flop,
    )


def _audit(pages: Sequence[PageInventory]) -> AuditReport:
    ctx, report = _ctx(), _report(pages)
    pm_version, pm_text = load_prompt("pattern_miner")
    miner = PatternMinerService(
        reasoning=MockReasoningAdapter(clock=lambda: FIXED),
        system_prompt=pm_text,
        prompt_version=pm_version,
        cost_tracker=_cost(),
        clock=lambda: FIXED,
    )
    patterns = miner.run(ctx, report, pages)
    ga_version, ga_text = load_prompt("geo_auditor")
    auditor = GeoAuditorService(
        reasoning=MockReasoningAdapter(clock=lambda: FIXED),
        system_prompt=ga_text,
        prompt_version=ga_version,
        cost_tracker=_cost(),
        clock=lambda: FIXED,
    )
    return auditor.run(ctx, report, pages, patterns)


def _patterns(pages: Sequence[PageInventory]) -> PatternReport:
    ctx, report = _ctx(), _report(pages)
    pm_version, pm_text = load_prompt("pattern_miner")
    miner = PatternMinerService(
        reasoning=MockReasoningAdapter(clock=lambda: FIXED),
        system_prompt=pm_text,
        prompt_version=pm_version,
        cost_tracker=_cost(),
        clock=lambda: FIXED,
    )
    return miner.run(ctx, report, pages)


def _service(reasoning: object) -> FixAgentService:
    version, text = load_prompt("fix_agent")
    return FixAgentService(
        reasoning=reasoning,  # type: ignore[arg-type]
        system_prompt=text,
        prompt_version=version,
        cost_tracker=_cost(),
        clock=lambda: FIXED,
    )


def test_fix_agent_prioritized_proposals() -> None:
    pages = build_sample_inventory()
    audit, patterns = _audit(pages), _patterns(pages)
    plan = _service(MockReasoningAdapter(clock=lambda: FIXED)).run(_ctx(), audit, patterns, pages)

    assert len(plan.proposals) >= 3
    ranks = [pyramid_rank(p.pyramid_level) for p in plan.proposals]
    assert ranks == sorted(ranks)  # nach Pyramide priorisiert
    finding_ids = {f.finding_id for f in audit.findings}
    for p in plan.proposals:
        assert p.finding_id in finding_ids  # jede Proposal verweist auf ein echtes Finding
        assert p.proposed_content
        assert p.rationale
        assert 0.0 <= p.confidence <= 1.0


class _ErrorOnceReasoning:
    """Liefert beim ersten Aufruf ERROR, danach die Mock-Antwort (Retry-Pfad)."""

    model = "stub"

    def __init__(self) -> None:
        self._calls = 0
        self._mock = MockReasoningAdapter(clock=lambda: FIXED)

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        self._calls += 1
        if self._calls == 1:
            return ReasoningResult(
                run_id=request.run_id,
                task=request.task,
                model=self.model,
                status=ReasoningStatus.ERROR,
                error="boom",
                generated_at=FIXED,
            )
        return self._mock.reason(request)


def test_fix_agent_retries_after_error() -> None:
    pages = build_sample_inventory()
    audit, patterns = _audit(pages), _patterns(pages)
    reasoning = _ErrorOnceReasoning()
    plan = _service(reasoning).run(_ctx(), audit, patterns, pages)
    assert reasoning._calls == 2  # ein Fehler + ein erfolgreicher Retry
    assert len(plan.proposals) >= 1


class _OneBadItemReasoning:
    """Liefert eine gute + eine schema-invalide Proposal (Drop-and-log-Pfad)."""

    model = "stub"

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        payload = {
            "proposals": [
                {
                    "patch_id": "px-f1-insert_block",
                    "finding_id": "f1",
                    "target_url": "https://www.it-sicherheit.de/firewall-grundlagen",
                    "lever": "fact_density",
                    "pyramid_level": "substance",
                    "change_type": "insert_block",
                    "proposed_content": "Konkreter Faktenblock.",
                    "rationale": "Template t2.",
                    "confidence": 0.8,
                },
                {"patch_id": "kaputt", "lever": "nonexistent"},  # invalide -> wird verworfen
            ]
        }
        return ReasoningResult(
            run_id=request.run_id,
            task=request.task,
            model=self.model,
            text=json.dumps(payload),
            usage=ReasoningUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            status=ReasoningStatus.OK,
            generated_at=FIXED,
        )


def test_fix_agent_drops_invalid_items() -> None:
    pages = build_sample_inventory()
    audit, patterns = _audit(pages), _patterns(pages)
    plan = _service(_OneBadItemReasoning()).run(_ctx(), audit, patterns, pages)
    assert [p.patch_id for p in plan.proposals] == ["px-f1-insert_block"]


class _EmptyReasoning:
    model = "stub"

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        return ReasoningResult(
            run_id=request.run_id,
            task=request.task,
            model=self.model,
            text='{"proposals": []}',
            status=ReasoningStatus.OK,
            generated_at=FIXED,
        )


def test_fix_agent_raises_when_no_valid_proposals() -> None:
    pages = build_sample_inventory()
    audit, patterns = _audit(pages), _patterns(pages)
    with pytest.raises(ReasoningError):
        _service(_EmptyReasoning()).run(_ctx(), audit, patterns, pages)
