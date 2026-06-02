"""Phase-1-Gate: pure Aggregations-/Bewertungslogik (Sampler-Mathematik)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from geo_audit_loop.domain.metrics import (
    aggregate_probes,
    count_target_url_citations,
    evaluate_target,
    host_matches_domain,
    normalize_url,
    url_host,
)
from geo_audit_loop.domain.probe import Citation, EngineId, ProbeResult, ProbeStatus

FIXED = datetime(2026, 1, 1, 12, 0, 0)
TARGET = "it-sicherheit.de"


def _cite(url: str, rank: int) -> Citation:
    return Citation(url=url, engine=EngineId.PERPLEXITY, rank=rank)


def _result(
    prompt_id: str,
    citations: Sequence[Citation],
    *,
    engine: EngineId = EngineId.PERPLEXITY,
    mentioned: bool = False,
    status: ProbeStatus = ProbeStatus.OK,
) -> ProbeResult:
    cited, rank = evaluate_target(citations, TARGET)
    return ProbeResult(
        run_id="run-1",
        engine_id=engine,
        model="m",
        prompt_id=prompt_id,
        prompt_version="v1",
        citations=tuple(citations),
        target_cited=cited,
        target_rank=rank,
        mentioned=mentioned,
        status=status,
        probed_at=FIXED,
    )


def test_url_host_strips_www() -> None:
    assert url_host("https://www.it-sicherheit.de/x") == "it-sicherheit.de"


def test_normalize_url() -> None:
    assert normalize_url("https://www.it-sicherheit.de/a/b/") == "https://it-sicherheit.de/a/b"
    assert normalize_url("http://IT-Sicherheit.DE/") == "http://it-sicherheit.de/"
    assert normalize_url("https://x.de/p?id=7") == "https://x.de/p?id=7"


def test_host_matches_domain() -> None:
    assert host_matches_domain("it-sicherheit.de", TARGET)
    assert host_matches_domain("blog.it-sicherheit.de", TARGET)
    assert not host_matches_domain("evil-it-sicherheit.de", TARGET)
    assert not host_matches_domain("it-sicherheit.de.evil.com", TARGET)


def test_evaluate_target_finds_first_match_position() -> None:
    cites = [
        _cite("https://other.com/a", 1),
        _cite("https://it-sicherheit.de/nis2", 2),
    ]
    cited, rank = evaluate_target(cites, TARGET)
    assert cited is True
    assert rank == 2


def test_evaluate_target_absent() -> None:
    cited, rank = evaluate_target([_cite("https://other.com/a", 1)], TARGET)
    assert cited is False
    assert rank is None


def test_aggregate_probes_rates_and_median() -> None:
    target = "https://it-sicherheit.de/nis2"
    results = [
        _result("p1", [_cite("https://o.com/x", 1), _cite(target, 2)], mentioned=True),
        _result("p1", [_cite(target, 1)], mentioned=True),
        _result("p1", [_cite(target, 3)], mentioned=False),
        _result("p1", [_cite("https://o.com/y", 1)], mentioned=True),
        _result("p1", [_cite("https://o.com/z", 1)], mentioned=False),
    ]
    aggs = aggregate_probes(results)
    assert len(aggs) == 1
    agg = aggs[0]
    assert agg.n_probes == 5
    assert agg.citation_rate == 0.6  # 3 von 5
    assert agg.mention_rate == 0.6  # 3 von 5
    assert agg.median_target_rank == 2.0  # median([2,1,3])


def test_aggregate_probes_ignores_errors_in_denominator() -> None:
    results = [
        _result("p1", [_cite("https://it-sicherheit.de/a", 1)]),
        _result("p1", [], status=ProbeStatus.ERROR),
    ]
    agg = aggregate_probes(results)[0]
    assert agg.n_probes == 1
    assert agg.citation_rate == 1.0


def test_count_target_url_citations_counts_once_per_probe() -> None:
    url = "https://it-sicherheit.de/nis2"
    results = [
        _result("p1", [_cite(url, 3), _cite(url + "/", 5)]),  # dieselbe URL doppelt -> 1x
        _result("p2", [_cite(url, 1)]),
        _result("p3", [_cite("https://other.com/x", 1)]),
    ]
    stats = count_target_url_citations(results, TARGET)
    assert len(stats) == 1
    assert stats[0].url == "https://it-sicherheit.de/nis2"
    assert stats[0].citation_count == 2
    assert stats[0].best_rank == 1
