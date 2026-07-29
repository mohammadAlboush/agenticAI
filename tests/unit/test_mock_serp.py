"""WP-B-Gate: MockSerpAdapter — Determinismus, Seed-Sensitivitaet, Overlap, target_rank."""

from __future__ import annotations

from datetime import datetime

from geo_audit_loop.adapters.sample_data import sample_target_urls
from geo_audit_loop.adapters.serp.mock import MockSerpAdapter
from geo_audit_loop.domain.probe import ProbeStatus
from geo_audit_loop.domain.serp import SerpProvider, SerpQuery, SerpRequest

FIXED = datetime(2026, 1, 1, 12, 0, 0)
QUERY_IDS = [f"q{i:02d}" for i in range(1, 13)]
# Fremd-URLs, die auch der Engine-Mock zitiert (Quelle: adapters/engines/mock.py).
ENGINE_EXTERNAL_URLS = {
    "https://www.bsi.bund.de/grundschutz",
    "https://de.wikipedia.org/wiki/IT-Sicherheit",
    "https://www.heise.de/security",
}


def _adapter(seed: int = 42) -> MockSerpAdapter:
    return MockSerpAdapter(seed=seed, clock=lambda: FIXED)


def _request(query_id: str = "q01", top_k: int = 10) -> SerpRequest:
    query = SerpQuery(query_id=query_id, text=f"Keyword-Query {query_id}", prompt_id="p01")
    return SerpRequest(run_id="run-1", query=query, top_k=top_k)


def _all_entries(seed: int) -> list[tuple[str, str, int]]:
    adapter = _adapter(seed)
    return [
        (query_id, entry.url, entry.position)
        for query_id in QUERY_IDS
        for entry in adapter.search(_request(query_id)).entries
    ]


def test_result_fields_and_provider() -> None:
    result = _adapter().search(_request("q03"))
    assert _adapter().provider is SerpProvider.MOCK
    assert result.provider is SerpProvider.MOCK
    assert result.run_id == "run-1"
    assert result.query_id == "q03"
    assert result.prompt_id == "p01"
    assert result.query_text == "Keyword-Query q03"
    assert result.status is ProbeStatus.OK
    assert result.fetched_at == FIXED
    assert result.latency_ms == 0


def test_deterministic_for_same_seed() -> None:
    assert _all_entries(seed=42) == _all_entries(seed=42)


def test_seed_sensitivity() -> None:
    assert _all_entries(seed=42) != _all_entries(seed=43)


def test_positions_contiguous_and_top_k_respected() -> None:
    full = _adapter().search(_request("q01"))
    assert [e.position for e in full.entries] == list(range(1, 11))

    small = _adapter().search(_request("q01", top_k=3))
    assert [e.position for e in small.entries] == [1, 2, 3]


def test_partial_overlap_with_engine_citations() -> None:
    urls = {url for _q, url, _p in _all_entries(seed=42)}
    # Mindestens ein Fremdtreffer, den auch der Engine-Mock zitiert ...
    assert urls & ENGINE_EXTERNAL_URLS
    # ... und mindestens ein Fremdtreffer, den der Engine-Mock NIE zitiert.
    targets = set(sample_target_urls())
    assert urls - ENGINE_EXTERNAL_URLS - targets


def test_target_rank_varies_across_queries() -> None:
    targets = set(sample_target_urls())
    ranks: dict[str, int | None] = {}
    adapter = _adapter()
    for query_id in QUERY_IDS:
        result = adapter.search(_request(query_id))
        positions = [e.position for e in result.entries if e.url in targets]
        ranks[query_id] = min(positions) if positions else None
    # Ziel-Domain rankt in manchen Queries (target_rank 1..10), in anderen nicht (None).
    assert any(rank is not None for rank in ranks.values())
    assert any(rank is None for rank in ranks.values())
    assert all(1 <= rank <= 10 for rank in ranks.values() if rank is not None)
