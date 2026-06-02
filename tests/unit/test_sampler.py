"""Phase-6-Gate: Sampler-Matrix, Checkpoint-Resume und Budget-Abbruch."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from geo_audit_loop.adapters.engines.mock import MockEngineAdapter
from geo_audit_loop.adapters.proxy.webshare import WebshareProxyPool
from geo_audit_loop.adapters.sample_data import sample_target_urls
from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
from geo_audit_loop.agents.sampler import SamplerService
from geo_audit_loop.domain.errors import BudgetExceeded
from geo_audit_loop.domain.probe import (
    EngineId,
    EngineProbeSpec,
    ProbePrompt,
    ProbeRequest,
    ProbeResult,
)
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.ports.engine import EnginePort

FIXED = datetime(2026, 1, 1, 12, 0, 0)
PROMPTS = [ProbePrompt(prompt_id="p1", text="q1"), ProbePrompt(prompt_id="p2", text="q2")]
PROXIES = [f"http://u:p@10.0.0.{i}:8000" for i in range(5)]
N_IPS = 5


class _CountingEngine:
    def __init__(self, inner: EnginePort) -> None:
        self._inner = inner
        self.calls = 0

    @property
    def engine_id(self) -> EngineId:
        return self._inner.engine_id

    def probe(self, request: ProbeRequest) -> ProbeResult:
        self.calls += 1
        return self._inner.probe(request)


def _ctx() -> RunContext:
    return RunContext(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        started_at=FIXED,
        seed=42,
        prompt_set_version="v1",
        config_hash="h",
    )


def _engines() -> dict[EngineId, _CountingEngine]:
    targets = sample_target_urls()
    return {
        EngineId.PERPLEXITY: _CountingEngine(
            MockEngineAdapter(EngineId.PERPLEXITY, target_urls=targets, seed=1, clock=lambda: FIXED)
        ),
        EngineId.CLAUDE: _CountingEngine(
            MockEngineAdapter(EngineId.CLAUDE, target_urls=targets, seed=2, clock=lambda: FIXED)
        ),
    }


def _specs() -> dict[EngineId, EngineProbeSpec]:
    return {
        engine_id: EngineProbeSpec(
            engine_id=engine_id, model="mock", max_tokens=256, temperature=0.2
        )
        for engine_id in (EngineId.PERPLEXITY, EngineId.CLAUDE)
    }


def _sampler(
    storage: SqliteStorage,
    engines: dict[EngineId, _CountingEngine],
    *,
    max_probes: int = 1000,
) -> SamplerService:
    return SamplerService(
        engines=engines,
        specs=_specs(),
        proxy=WebshareProxyPool(PROXIES, seed=42),
        storage=storage,
        cost_tracker=CostTracker(max_probes=max_probes, max_usd=1000.0, max_tokens=10**9),
        n_proxy_ips=N_IPS,
    )


def _storage(tmp_path: Path) -> SqliteStorage:
    storage = SqliteStorage(tmp_path / "db.sqlite")
    storage.initialize()
    return storage


def test_full_matrix_size_and_aggregates(tmp_path: Path) -> None:
    engines = _engines()
    storage = _storage(tmp_path)
    aggregates = _sampler(storage, engines).run(_ctx(), PROMPTS)
    assert len(storage.load_probes("run-1")) == 2 * 2 * N_IPS  # 20
    assert len(aggregates) == 2 * 2  # (Engine x Prompt)
    assert all(agg.n_probes == N_IPS for agg in aggregates)
    assert sum(engine.calls for engine in engines.values()) == 20


def test_checkpoint_resume_skips_completed(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _sampler(storage, _engines()).run(_ctx(), PROMPTS)

    fresh_engines = _engines()
    _sampler(storage, fresh_engines).run(_ctx(), PROMPTS)
    assert sum(engine.calls for engine in fresh_engines.values()) == 0
    assert len(storage.load_probes("run-1")) == 20


def test_budget_cap_aborts_and_persists_checkpoint(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    sampler = _sampler(storage, _engines(), max_probes=3)
    with pytest.raises(BudgetExceeded):
        sampler.run(_ctx(), PROMPTS)
    assert len(storage.load_probes("run-1")) == 3
