"""Unit: Entity-Extractor mit deterministischem Mock-Reasoning (kein Netz, Session 8)."""

from __future__ import annotations

from datetime import datetime

import pytest

from geo_audit_loop.adapters.reasoning.mock import MockReasoningAdapter
from geo_audit_loop.adapters.sample_data import build_sample_inventory
from geo_audit_loop.agents.entity_extractor import EntityExtractorService
from geo_audit_loop.config.pricing import PRICE_TABLE
from geo_audit_loop.domain.entity import EntityGraphReport, build_entity_graph
from geo_audit_loop.domain.errors import ReasoningError
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.reasoning import (
    ReasoningRequest,
    ReasoningResult,
    ReasoningStatus,
    ReasoningUsage,
)
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.ports.reasoning import ReasoningPort
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


def _pages() -> list[PageInventory]:
    return build_sample_inventory("it-sicherheit.de")


def _graph(pages: list[PageInventory]) -> EntityGraphReport:
    return build_entity_graph("it-sicherheit.de", pages, run_id="t", generated_at=FIXED)


def _extractor(
    reasoning: ReasoningPort | None = None, max_same_as: int = 5
) -> EntityExtractorService:
    version, text = load_prompt("entity_extractor")
    return EntityExtractorService(
        reasoning=reasoning if reasoning is not None else MockReasoningAdapter(clock=lambda: FIXED),
        system_prompt=text,
        prompt_version=version,
        cost_tracker=_cost(),
        max_same_as=max_same_as,
        clock=lambda: FIXED,
    )


def test_extracts_validated_same_as() -> None:
    pages = _pages()
    same_as = _extractor().run(_ctx(), _graph(pages), pages)
    assert same_as  # nicht leer
    assert all(url.startswith(("http://", "https://")) for url in same_as)  # nur absolute URLs
    assert len(same_as) == len(set(same_as))  # keine Dubletten
    assert not any(url.startswith("/") for url in same_as)  # relative Pfade gefiltert


def test_caps_same_as() -> None:
    pages = _pages()
    same_as = _extractor(max_same_as=2).run(_ctx(), _graph(pages), pages)
    assert len(same_as) <= 2


class _FixedReasoning:
    model = "mock-reasoner-v1"

    def __init__(self, text: str) -> None:
        self._text = text

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        return ReasoningResult(
            run_id=request.run_id,
            task=request.task,
            model=self.model,
            text=self._text,
            usage=ReasoningUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            status=ReasoningStatus.OK,
            generated_at=FIXED,
        )


def test_empty_same_as_is_allowed_no_raise() -> None:
    pages = _pages()
    extractor = _extractor(reasoning=_FixedReasoning('{"same_as": []}'))
    assert extractor.run(_ctx(), _graph(pages), pages) == ()


def test_malformed_json_raises_after_retries() -> None:
    pages = _pages()
    extractor = _extractor(reasoning=_FixedReasoning('{"kein_feld": 1}'))
    with pytest.raises(ReasoningError):
        extractor.run(_ctx(), _graph(pages), pages)
