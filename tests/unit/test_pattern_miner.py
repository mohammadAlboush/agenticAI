"""Unit: Pattern-Miner mit deterministischem Mock-Reasoning (kein Netz)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from geo_audit_loop.adapters.reasoning.mock import MockReasoningAdapter
from geo_audit_loop.adapters.sample_data import build_sample_inventory
from geo_audit_loop.agents.pattern_miner import PatternMinerService
from geo_audit_loop.config.pricing import PRICE_TABLE
from geo_audit_loop.domain.findings import TopFlopEntry, TopFlopReport
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.run import RunContext
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


def _miner() -> PatternMinerService:
    version, text = load_prompt("pattern_miner")
    return PatternMinerService(
        reasoning=MockReasoningAdapter(clock=lambda: FIXED),
        system_prompt=text,
        prompt_version=version,
        cost_tracker=_cost(),
        clock=lambda: FIXED,
    )


def test_pattern_miner_extracts_anchored_templates() -> None:
    pages = build_sample_inventory()
    report = _miner().run(_ctx(), _report(pages), pages)
    assert len(report.templates) >= 2
    for template in report.templates:
        assert template.levers
        assert all(isinstance(lever, Lever) for lever in template.levers)
        assert isinstance(template.pyramid_level, PyramidLevel)
        assert 0.0 <= template.confidence <= 1.0
        assert template.evidence_urls
