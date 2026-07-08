"""Eval (toleranzbasiert): der Entity-Extractor (LLM) findet sameAs-Autoritaets-URLs.

Der Entity-Extractor ist nicht-deterministisch (LLM); der Eval prueft daher **Eigenschaften**
statt exakter Gleichheit (tests/eval/README.md, Projektregeln §5.3): genug valide sameAs-URLs,
alle absolut (http/https), keine Dubletten, Kappung eingehalten. Offline laeuft er gegen den
deterministischen Mock -> reproduzierbar.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from geo_audit_loop.adapters.reasoning.mock import MockReasoningAdapter
from geo_audit_loop.adapters.sample_data import build_sample_inventory
from geo_audit_loop.agents.entity_extractor import EntityExtractorService
from geo_audit_loop.config.pricing import PRICE_TABLE
from geo_audit_loop.domain.entity import build_entity_graph
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.prompts.loader import load_prompt

FIXED = datetime(2026, 1, 1, 12, 0, 0)
GOLDEN = Path(__file__).parent / "golden" / "entity_extractor_seed42.json"


def test_entity_extractor_within_tolerance() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    max_same_as = int(golden["max_same_as"])

    ee_version, ee_prompt = load_prompt("entity_extractor")
    extractor = EntityExtractorService(
        reasoning=MockReasoningAdapter(clock=lambda: FIXED),
        system_prompt=ee_prompt,
        prompt_version=ee_version,
        cost_tracker=CostTracker(
            max_probes=1000, max_usd=10.0, max_tokens=10_000_000, price_table=PRICE_TABLE
        ),
        max_same_as=max_same_as,
        clock=lambda: FIXED,
    )
    pages = build_sample_inventory(golden["domain"])
    graph = build_entity_graph(golden["domain"], pages, run_id="eval-ee", generated_at=FIXED)
    ctx = RunContext(
        run_id="eval-ee",
        target_domain=golden["domain"],
        started_at=FIXED,
        seed=golden["seed"],
        prompt_set_version=golden["prompt_set_version"],
        config_hash="hash",
    )
    same_as = extractor.run(ctx, graph, pages)

    assert len(same_as) >= golden["min_same_as"]
    assert len(same_as) <= max_same_as  # Kappung
    assert all(url.startswith(("http://", "https://")) for url in same_as)  # nur absolute URLs
    assert len(same_as) == len(set(same_as))  # keine Dubletten
