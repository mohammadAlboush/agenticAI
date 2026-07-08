"""Eval (toleranzbasiert): der Query-Generator (LLM) fuellt die schwachen Intents.

Der Query-Generator ist nicht-deterministisch (LLM); der Eval prueft daher **Eigenschaften**
statt exakter Gleichheit (tests/eval/README.md, Projektregeln §5.3): fuer die vorgegebenen
schwachen Intents werden genug valide Luecken-Fragen erzeugt, jede Frage traegt einen der
angeforderten Intents, und die Kappung je Intent wird eingehalten. Offline laeuft er gegen
den deterministischen Mock -> reproduzierbar.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from geo_audit_loop.adapters.reasoning.mock import MockReasoningAdapter
from geo_audit_loop.agents.query_generator import QueryGeneratorService
from geo_audit_loop.config.pricing import PRICE_TABLE
from geo_audit_loop.domain.coverage import CoverageReport, IntentCoverage
from geo_audit_loop.domain.probe import QueryIntent
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.prompts.loader import load_probe_set, load_prompt

FIXED = datetime(2026, 1, 1, 12, 0, 0)
GOLDEN = Path(__file__).parent / "golden" / "query_generator_seed42.json"


def test_query_generator_within_tolerance() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    weak = tuple(QueryIntent(value) for value in golden["weak_intents"])
    max_per_intent = int(golden["max_per_intent"])

    version, prompts = load_probe_set(golden["prompt_set_version"])
    qg_version, qg_prompt = load_prompt("query_generator")
    generator = QueryGeneratorService(
        reasoning=MockReasoningAdapter(clock=lambda: FIXED),
        system_prompt=qg_prompt,
        prompt_version=qg_version,
        cost_tracker=CostTracker(
            max_probes=1000, max_usd=10.0, max_tokens=10_000_000, price_table=PRICE_TABLE
        ),
        prompts=prompts,
        max_per_intent=max_per_intent,
        clock=lambda: FIXED,
    )
    coverage = CoverageReport(
        run_id="eval-qg",
        target_domain=golden["domain"],
        generated_at=FIXED,
        n_probes=48,
        overall_citation_rate=0.3,
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
    ctx = RunContext(
        run_id="eval-qg",
        target_domain=golden["domain"],
        started_at=FIXED,
        seed=golden["seed"],
        prompt_set_version=version,
        config_hash="hash",
    )
    queries = generator.run(ctx, coverage)

    assert len(queries) >= golden["min_queries"]
    assert all(q.intent in set(weak) for q in queries)  # nur angeforderte Intents
    assert all(q.text.strip() for q in queries)
    covered = {q.intent for q in queries}
    assert len(covered) >= golden["min_intents_covered"]
    per_intent: dict[QueryIntent, int] = {}
    for query in queries:
        per_intent[query.intent] = per_intent.get(query.intent, 0) + 1
    assert all(count <= max_per_intent for count in per_intent.values())  # Kappung
    # Keine Text-Dubletten.
    texts = [q.text.strip().lower() for q in queries]
    assert len(texts) == len(set(texts))
