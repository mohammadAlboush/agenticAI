"""Unit: SERP-/Overlap-Contracts — compute_overlap-Mathematik (rein, deterministisch)."""

from __future__ import annotations

from datetime import datetime

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain.overlap import OverlapReport, compute_overlap
from geo_audit_loop.domain.probe import Citation, EngineId, ProbeResult, ProbeStatus
from geo_audit_loop.domain.serp import (
    RankEntry,
    SerpProvider,
    SerpQuery,
    SerpRequest,
    SerpResult,
)

FIXED = datetime(2026, 1, 1, 12, 0, 0)
TARGET = "it-sicherheit.de"


def _serp(
    query_id: str = "q01",
    prompt_id: str = "p01",
    urls: tuple[str, ...] = (),
    status: ProbeStatus = ProbeStatus.OK,
) -> SerpResult:
    return SerpResult(
        run_id="run-1",
        provider=SerpProvider.MOCK,
        query_id=query_id,
        prompt_id=prompt_id,
        query_text="nis2 anforderungen",
        entries=tuple(RankEntry(url=url, position=idx) for idx, url in enumerate(urls, start=1)),
        status=status,
        fetched_at=FIXED,
    )


def _probe(
    prompt_id: str = "p01",
    citations: tuple[str, ...] = (),
    target_cited: bool = False,
    status: ProbeStatus = ProbeStatus.OK,
) -> ProbeResult:
    return ProbeResult(
        run_id="run-1",
        engine_id=EngineId.GEMINI,
        model="m",
        prompt_id=prompt_id,
        prompt_version="v1",
        citations=tuple(Citation(url=url, engine=EngineId.GEMINI) for url in citations),
        target_cited=target_cited,
        status=status,
        probed_at=FIXED,
    )


def _compute(serp_results: list[SerpResult], probes: list[ProbeResult]) -> OverlapReport:
    return compute_overlap(
        run_id="run-1",
        target_domain=TARGET,
        provider=SerpProvider.MOCK,
        query_set_version="v1",
        serp_results=serp_results,
        probes=probes,
        generated_at=FIXED,
    )


def test_empty_ai_set_yields_zero_shares() -> None:
    # Keine AI-Zitate: jaccard 0, ai_in_serp_share 0 (kein Division-durch-Null-Crash).
    report = _compute([_serp(urls=("https://bsi.bund.de/nis2",))], [_probe(citations=())])
    stat = report.stats[0]
    assert stat.jaccard == 0.0
    assert stat.ai_in_serp_share == 0.0
    assert stat.domain_jaccard == 0.0
    assert stat.n_serp_urls == 1
    assert stat.n_ai_urls == 0


def test_full_overlap_yields_one() -> None:
    urls = ("https://bsi.bund.de/nis2", "https://it-sicherheit.de/nis2")
    report = _compute([_serp(urls=urls)], [_probe(citations=urls, target_cited=True)])
    stat = report.stats[0]
    assert stat.jaccard == 1.0
    assert stat.ai_in_serp_share == 1.0
    assert stat.domain_jaccard == 1.0
    assert stat.target_ai_citation_rate == 1.0
    assert report.mean_jaccard == 1.0


def test_url_vs_host_level_distinction() -> None:
    # Gleicher Host, andere Seite: URL-Jaccard 0, Host-Jaccard 1.
    report = _compute(
        [_serp(urls=("https://bsi.bund.de/nis2",))],
        [_probe(citations=("https://bsi.bund.de/ransomware",))],
    )
    stat = report.stats[0]
    assert stat.jaccard == 0.0
    assert stat.domain_jaccard == 1.0


def test_url_normalization_matches_www_and_trailing_slash() -> None:
    # www./Trailing-Slash-Varianten derselben Seite zaehlen als Treffer (normalize_url).
    report = _compute(
        [_serp(urls=("https://www.bsi.bund.de/nis2/",))],
        [_probe(citations=("https://bsi.bund.de/nis2",))],
    )
    assert report.stats[0].jaccard == 1.0


def test_rounding_to_six_decimals() -> None:
    # 1 gemeinsame von 3 URLs insgesamt -> 1/3 = 0.333333 (6 Nachkommastellen).
    report = _compute(
        [_serp(urls=("https://a.de/x", "https://b.de/x"))],
        [_probe(citations=("https://a.de/x", "https://c.de/x"))],
    )
    stat = report.stats[0]
    assert stat.jaccard == 0.333333
    assert stat.ai_in_serp_share == 0.5
    assert report.mean_jaccard == 0.333333


def test_prompt_join_and_sort_by_query_id() -> None:
    # Jede Query joint NUR die Probes ihres Prompts; Ergebnis nach query_id sortiert.
    serps = [
        _serp("q02", "p02", urls=("https://b.de/x",)),
        _serp("q01", "p01", urls=("https://a.de/x",)),
    ]
    probes = [
        _probe("p01", citations=("https://a.de/x",)),
        _probe("p02", citations=("https://other.de/x",)),
    ]
    report = _compute(serps, probes)
    assert [s.query_id for s in report.stats] == ["q01", "q02"]
    assert report.stats[0].jaccard == 1.0  # p01 trifft
    assert report.stats[1].jaccard == 0.0  # p02 trifft nicht
    assert report.n_queries == 2


def test_error_serp_results_and_error_probes_are_skipped() -> None:
    serps = [
        _serp("q01", "p01", urls=("https://a.de/x",)),
        _serp("q02", "p02", urls=("https://b.de/x",), status=ProbeStatus.ERROR),
    ]
    probes = [
        _probe("p01", citations=("https://a.de/x",)),
        _probe("p01", citations=("https://zzz.de/x",), status=ProbeStatus.ERROR),
    ]
    report = _compute(serps, probes)
    assert report.n_queries == 1  # ERROR-SERP faellt raus
    assert report.stats[0].jaccard == 1.0  # ERROR-Probe verduennt die AI-Menge nicht


def test_target_serp_rank_is_best_position() -> None:
    report = _compute(
        [
            _serp(
                urls=(
                    "https://bsi.bund.de/nis2",
                    "https://www.it-sicherheit.de/nis2",
                    "https://it-sicherheit.de/nis2-faq",
                )
            )
        ],
        [_probe()],
    )
    assert report.stats[0].target_serp_rank == 2  # beste (kleinste) Ziel-Position


def test_target_rank_none_when_target_absent() -> None:
    report = _compute([_serp(urls=("https://bsi.bund.de/nis2",))], [_probe()])
    assert report.stats[0].target_serp_rank is None


def test_target_ai_citation_rate_over_ok_probes() -> None:
    probes = [
        _probe(target_cited=True),
        _probe(target_cited=False),
        _probe(target_cited=True, status=ProbeStatus.ERROR),  # zaehlt nicht
    ]
    report = _compute([_serp(urls=("https://a.de/x",))], probes)
    assert report.stats[0].target_ai_citation_rate == 0.5


def test_determinism_same_input_same_report() -> None:
    serps = [_serp(urls=("https://a.de/x", "https://b.de/x"))]
    probes = [_probe(citations=("https://b.de/x", "https://c.de/x"))]
    assert _compute(serps, probes) == _compute(serps, probes)


def test_empty_inputs_yield_empty_report() -> None:
    report = _compute([], [])
    assert report.n_queries == 0
    assert report.stats == ()
    assert report.mean_jaccard == 0.0
    assert report.mean_ai_in_serp_share == 0.0


def test_serp_request_defaults_from_constants() -> None:
    request = SerpRequest(
        run_id="run-1", query=SerpQuery(query_id="q01", text="nis2", prompt_id="p01")
    )
    assert request.top_k == c.SERP_TOP_K
    assert request.gl == c.SERP_GL
    assert request.hl == c.SERP_HL
