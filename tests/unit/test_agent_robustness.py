"""Unit: Robustheit der LLM-Agenten gegen fehlerhafte Reasoning-Ausgaben.

Prueft den graceful-degradation-Pfad (ungueltige Items werden verworfen, gueltige behalten)
und den Retry-dann-Fehler-Pfad (komplett unparsebare Antwort) - mit einem konfigurierbaren
Reasoning-Stub statt echtem LLM.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

import pytest

from geo_audit_loop.adapters.sample_data import build_sample_inventory
from geo_audit_loop.agents.geo_auditor import GeoAuditorService
from geo_audit_loop.agents.pattern_miner import PatternMinerService
from geo_audit_loop.config.pricing import PRICE_TABLE
from geo_audit_loop.domain.errors import ReasoningError
from geo_audit_loop.domain.findings import TopFlopEntry, TopFlopReport
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningResult
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.domain.templates import PatternReport, Template
from geo_audit_loop.observability.cost import CostTracker

FIXED = datetime(2026, 1, 1, 12, 0, 0)
_BASE = "https://www.it-sicherheit.de"


class _FixedReasoning:
    """Reasoning-Stub, der eine fest vorgegebene Antwort liefert (erfuellt ReasoningPort)."""

    model = "fixed-reasoner"

    def __init__(self, text: str) -> None:
        self._text = text

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        return ReasoningResult(
            run_id=request.run_id,
            task=request.task,
            model=self.model,
            text=self._text,
            generated_at=FIXED,
        )


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


_VALID_TEMPLATE = {
    "template_id": "t1",
    "title": "T",
    "summary": "S",
    "levers": ["answer_blocks"],
    "pyramid_level": "extractability",
    "criteria": ["c"],
    "evidence_urls": [_BASE],
    "confidence": 0.8,
}
_VALID_FINDING = {
    "finding_id": "f1",
    "target_url": f"{_BASE}/firewall-grundlagen",
    "lever": "definition_blocks",
    "pyramid_level": "extractability",
    "severity": "medium",
    "evidence": "e",
    "recommendation": "r",
    "template_id": "t1",
}


def _pattern_miner(text: str) -> PatternMinerService:
    return PatternMinerService(
        reasoning=_FixedReasoning(text),
        system_prompt="x",
        prompt_version="v1",
        cost_tracker=_cost(),
        clock=lambda: FIXED,
    )


def test_pattern_miner_drops_invalid_items_keeps_valid() -> None:
    text = json.dumps({"templates": [_VALID_TEMPLATE, {"template_id": "bad"}]})  # 2. Item ungueltig
    report = _pattern_miner(text).run(
        _ctx(), _report(build_sample_inventory()), build_sample_inventory()
    )
    assert len(report.templates) == 1  # ungueltiges Item verworfen, gueltiges behalten


def test_pattern_miner_raises_on_unparsable() -> None:
    miner = _pattern_miner("voellig kaputt, kein JSON")
    with pytest.raises(ReasoningError):
        miner.run(_ctx(), _report(build_sample_inventory()), build_sample_inventory())


def test_geo_auditor_drops_invalid_findings() -> None:
    pages = build_sample_inventory()
    patterns = PatternReport(
        run_id="t",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        templates=(Template.model_validate(_VALID_TEMPLATE),),
    )
    text = json.dumps({"findings": [_VALID_FINDING, {"finding_id": "bad"}]})
    auditor = GeoAuditorService(
        reasoning=_FixedReasoning(text),
        system_prompt="x",
        prompt_version="v1",
        cost_tracker=_cost(),
        clock=lambda: FIXED,
    )
    audit = auditor.run(_ctx(), _report(pages), pages, patterns)
    assert len(audit.findings) == 1
