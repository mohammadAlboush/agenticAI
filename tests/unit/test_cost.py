"""Phase-3-Gate: Kosten-Schaetzung und harter Budget-Cap."""

from __future__ import annotations

import pytest

from geo_audit_loop.config.pricing import Price
from geo_audit_loop.domain.errors import BudgetExceeded
from geo_audit_loop.domain.probe import ProbeUsage
from geo_audit_loop.observability.cost import CostTracker


def test_estimate_and_record_cost() -> None:
    tracker = CostTracker(
        max_probes=240,
        max_usd=2.0,
        max_tokens=1_000_000,
        price_table={"sonar-pro": Price(usd_per_1m_input=3.0, usd_per_1m_output=15.0)},
    )
    usage = ProbeUsage(prompt_tokens=1_000, completion_tokens=2_000, total_tokens=3_000)
    cost = tracker.record("sonar-pro", usage)
    # 1000/1e6*3 + 2000/1e6*15 = 0.003 + 0.030
    assert round(cost, 6) == 0.033
    snap = tracker.snapshot()
    assert snap.probes == 1
    assert snap.total_tokens == 3_000
    assert round(snap.total_usd, 6) == 0.033


def test_unknown_model_costs_zero() -> None:
    tracker = CostTracker(max_probes=10, max_usd=1.0, max_tokens=10_000)
    assert tracker.estimate_cost("mock", ProbeUsage(total_tokens=500)) == 0.0


def test_probe_cap_raises_budget_exceeded() -> None:
    tracker = CostTracker(max_probes=1, max_usd=10.0, max_tokens=10**9)
    tracker.ensure_can_probe()  # 0 < 1 -> ok
    tracker.record("mock", ProbeUsage(total_tokens=0))
    with pytest.raises(BudgetExceeded) as exc:
        tracker.ensure_can_probe()
    assert exc.value.limit_name == "max_probes"


def test_usd_cap_raises_after_overspend() -> None:
    tracker = CostTracker(
        max_probes=100,
        max_usd=0.01,
        max_tokens=10**9,
        price_table={"pricey": Price(usd_per_1m_output=1000.0)},
    )
    tracker.ensure_can_probe()
    # 1e6 completion-Tokens * 1000 USD/1M = 1.0 USD (> 0.01 Cap)
    tracker.record("pricey", ProbeUsage(completion_tokens=1_000_000, total_tokens=1_000_000))
    with pytest.raises(BudgetExceeded) as exc:
        tracker.ensure_can_probe()
    assert exc.value.limit_name == "max_usd"


def test_token_cap_uses_consistent_boundary() -> None:
    tracker = CostTracker(max_probes=100, max_usd=1000.0, max_tokens=1_000)
    tracker.ensure_can_probe()
    tracker.record("mock", ProbeUsage(total_tokens=1_000))  # erreicht exakt das Token-Limit
    with pytest.raises(BudgetExceeded) as exc:
        tracker.ensure_can_probe()
    assert exc.value.limit_name == "max_tokens"


def test_zero_budget_blocks_immediately() -> None:
    # Harter Cap: ein Null-Budget erlaubt keine Probe (einheitliche >=-Semantik).
    tracker = CostTracker(max_probes=5, max_usd=0.0, max_tokens=0)
    with pytest.raises(BudgetExceeded):
        tracker.ensure_can_probe()
