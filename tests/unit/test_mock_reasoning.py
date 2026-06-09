"""Unit: deterministischer Reasoning-Mock liefert stabile, schema-valide JSON-Antworten."""

from __future__ import annotations

import json
from datetime import datetime

from geo_audit_loop.adapters.reasoning.mock import MOCK_MODEL, MockReasoningAdapter
from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningStatus

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _req(task: str) -> ReasoningRequest:
    return ReasoningRequest(
        run_id="r", task=task, prompt_text="x", model="m", max_tokens=100, temperature=0.2
    )


def test_mock_is_deterministic_and_valid_json() -> None:
    adapter = MockReasoningAdapter(clock=lambda: FIXED)
    first = adapter.reason(_req("pattern_miner"))
    second = adapter.reason(_req("pattern_miner"))
    assert first.text == second.text  # deterministisch
    assert first.status is ReasoningStatus.OK
    assert first.model == MOCK_MODEL
    assert first.usage.total_tokens > 0
    data = json.loads(first.text)
    assert isinstance(data["templates"], list)
    assert data["templates"]


def test_mock_geo_auditor_payload() -> None:
    adapter = MockReasoningAdapter(clock=lambda: FIXED)
    data = json.loads(adapter.reason(_req("geo_auditor")).text)
    assert isinstance(data["findings"], list)
    assert data["findings"]


def test_mock_unknown_task_is_empty() -> None:
    adapter = MockReasoningAdapter(clock=lambda: FIXED)
    assert json.loads(adapter.reason(_req("other")).text) == {}
