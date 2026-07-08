"""Unit: Query-Generator mit deterministischem Mock-Reasoning (kein Netz, Session 4)."""

from __future__ import annotations

from datetime import datetime

from geo_audit_loop.adapters.reasoning.mock import MockReasoningAdapter
from geo_audit_loop.agents.query_generator import QueryGeneratorService
from geo_audit_loop.config.pricing import PRICE_TABLE
from geo_audit_loop.domain.coverage import CoverageReport, IntentCoverage
from geo_audit_loop.domain.probe import ProbePrompt, QueryIntent
from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningResult
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


def _prompts() -> list[ProbePrompt]:
    return [
        ProbePrompt(
            prompt_id="p1", text="Woran erkennt man Phishing?", intent=QueryIntent.TROUBLESHOOTING
        ),
        ProbePrompt(
            prompt_id="p2", text="Welcher Passwort-Manager?", intent=QueryIntent.COMPARISON
        ),
        ProbePrompt(prompt_id="p3", text="Was ist NIS2?", intent=QueryIntent.INFORMATIONAL),
    ]


def _coverage(*weak: QueryIntent) -> CoverageReport:
    return CoverageReport(
        run_id="t",
        target_domain="it-sicherheit.de",
        generated_at=FIXED,
        n_probes=48,
        overall_citation_rate=0.4,
        intents=tuple(
            IntentCoverage(
                intent=intent,
                n_prompts=1,
                n_covered=0,
                coverage_rate=0.0,
                mean_citation_rate=0.0,
            )
            for intent in weak
        ),
        weakest_intents=weak,
    )


def _generator(
    prompts: list[ProbePrompt] | None = None, max_per_intent: int = 3
) -> QueryGeneratorService:
    version, text = load_prompt("query_generator")
    return QueryGeneratorService(
        reasoning=MockReasoningAdapter(clock=lambda: FIXED),
        system_prompt=text,
        prompt_version=version,
        cost_tracker=_cost(),
        prompts=prompts if prompts is not None else _prompts(),
        max_per_intent=max_per_intent,
        clock=lambda: FIXED,
    )


def test_generates_queries_only_for_weak_intents() -> None:
    weak = (QueryIntent.TROUBLESHOOTING, QueryIntent.COMPARISON)
    queries = _generator().run(_ctx(), _coverage(*weak))
    assert queries  # nicht leer
    assert {q.intent for q in queries} <= set(weak)  # nur schwache Intents
    assert all(q.text for q in queries)


def test_no_weak_intents_returns_empty_without_reasoning() -> None:
    class _CountingReasoning:
        model = "mock-reasoner-v1"

        def __init__(self) -> None:
            self.calls = 0

        def reason(self, request: ReasoningRequest) -> ReasoningResult:
            self.calls += 1
            return ReasoningResult(
                run_id=request.run_id, task=request.task, model=self.model, generated_at=FIXED
            )

    spy = _CountingReasoning()
    version, text = load_prompt("query_generator")
    generator = QueryGeneratorService(
        reasoning=spy,
        system_prompt=text,
        prompt_version=version,
        cost_tracker=_cost(),
        prompts=_prompts(),
        clock=lambda: FIXED,
    )
    assert generator.run(_ctx(), _coverage()) == ()  # keine schwachen Intents
    assert spy.calls == 0  # kein LLM-Aufruf, kein Budget-Verbrauch


def test_caps_queries_per_intent() -> None:
    # Der Mock liefert 2 Fragen je Intent; max_per_intent=1 -> hoechstens 1 je Intent.
    queries = _generator(max_per_intent=1).run(
        _ctx(), _coverage(QueryIntent.TROUBLESHOOTING, QueryIntent.COMPARISON)
    )
    per_intent: dict[QueryIntent, int] = {}
    for query in queries:
        per_intent[query.intent] = per_intent.get(query.intent, 0) + 1
    assert all(count <= 1 for count in per_intent.values())


def test_filters_out_non_requested_intents() -> None:
    # Nur COMPARISON schwach -> keine troubleshooting/informational-Fragen im Ergebnis.
    queries = _generator().run(_ctx(), _coverage(QueryIntent.COMPARISON))
    assert queries
    assert all(q.intent is QueryIntent.COMPARISON for q in queries)
