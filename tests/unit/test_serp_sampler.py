"""WP-B-Gate: SERP-Sampler — Checkpoint-Resume und Pro-Provider-Quota-Stopp."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from geo_audit_loop.adapters.serp.mock import MockSerpAdapter
from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
from geo_audit_loop.agents.serp_sampler import SerpSamplerService
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.domain.serp import SerpProvider, SerpQuery, SerpRequest, SerpResult
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.ports.serp import SerpPort

FIXED = datetime(2026, 1, 1, 12, 0, 0)
QUERIES = [
    SerpQuery(query_id=f"q{i:02d}", text=f"Keyword-Query {i}", prompt_id=f"p{i:02d}")
    for i in range(1, 4)
]


class _CountingSerp:
    """Zaehlender Wrapper um einen echten ``SerpPort`` (misst externe Aufrufe)."""

    def __init__(self, inner: SerpPort) -> None:
        self._inner = inner
        self.calls = 0

    @property
    def provider(self) -> SerpProvider:
        return self._inner.provider

    def search(self, request: SerpRequest) -> SerpResult:
        self.calls += 1
        return self._inner.search(request)


def _ctx() -> RunContext:
    return RunContext(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        started_at=FIXED,
        seed=42,
        prompt_set_version="v1",
        config_hash="h",
    )


def _storage(tmp_path: Path) -> SqliteStorage:
    storage = SqliteStorage(tmp_path / "db.sqlite")
    storage.initialize()
    return storage


def _counting_serp() -> _CountingSerp:
    return _CountingSerp(MockSerpAdapter(seed=42, clock=lambda: FIXED))


def _tracker(request_limits: dict[str, int] | None = None) -> CostTracker:
    return CostTracker(
        max_probes=1000, max_usd=1000.0, max_tokens=10**9, request_limits=request_limits
    )


def _sampler(
    serp: _CountingSerp, storage: SqliteStorage, tracker: CostTracker
) -> SerpSamplerService:
    return SerpSamplerService(serp=serp, storage=storage, cost_tracker=tracker)


def test_all_queries_executed_and_persisted(tmp_path: Path) -> None:
    serp = _counting_serp()
    storage = _storage(tmp_path)
    tracker = _tracker()
    results = _sampler(serp, storage, tracker).run(_ctx(), QUERIES)
    assert serp.calls == len(QUERIES)
    assert [r.query_id for r in results] == ["q01", "q02", "q03"]
    assert len(storage.load_serp_results("run-1", SerpProvider.MOCK)) == len(QUERIES)
    # Provider ohne Limit-Eintrag: unbegrenzt, aber trotzdem verbucht.
    assert tracker.snapshot().requests_by_provider == {"mock": len(QUERIES)}


def test_checkpoint_resume_makes_zero_new_calls(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _sampler(_counting_serp(), storage, _tracker()).run(_ctx(), QUERIES)

    fresh = _counting_serp()
    results = _sampler(fresh, storage, _tracker()).run(_ctx(), QUERIES)
    assert fresh.calls == 0
    assert len(results) == len(QUERIES)


def test_provider_quota_stops_remaining_queries(tmp_path: Path) -> None:
    serp = _counting_serp()
    storage = _storage(tmp_path)
    tracker = _tracker(request_limits={"mock": 2})
    # Quote erschoepft -> KEINE Exception nach aussen, restliche Queries uebersprungen.
    results = _sampler(serp, storage, tracker).run(_ctx(), QUERIES)
    assert serp.calls == 2
    assert [r.query_id for r in results] == ["q01", "q02"]
    assert tracker.snapshot().requests_by_provider == {"mock": 2}


def test_quota_resume_continues_after_checkpoint(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _sampler(_counting_serp(), storage, _tracker(request_limits={"mock": 2})).run(_ctx(), QUERIES)

    # Neuer Lauf mit frischer Quote: erledigte Zellen bleiben uebersprungen,
    # nur die fehlende Query wird nachgeholt (Checkpoint + Quota kombiniert).
    fresh = _counting_serp()
    results = _sampler(fresh, storage, _tracker(request_limits={"mock": 2})).run(_ctx(), QUERIES)
    assert fresh.calls == 1
    assert [r.query_id for r in results] == ["q01", "q02", "q03"]
