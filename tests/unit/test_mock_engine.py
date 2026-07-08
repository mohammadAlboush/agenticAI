"""Phase-4-Gate: deterministischer Mock-Engine-Adapter."""

from __future__ import annotations

from datetime import datetime

from geo_audit_loop.adapters.engines.mock import MockEngineAdapter
from geo_audit_loop.domain.probe import EngineId, ProbeRequest, ProbeStatus

FIXED = datetime(2026, 1, 1, 12, 0, 0)
TARGETS = [f"https://www.it-sicherheit.de/p{i}" for i in range(5)]


def _req(prompt_id: str = "p1", proxy_label: str = "proxy-0") -> ProbeRequest:
    return ProbeRequest(
        run_id="run-1",
        engine_id=EngineId.PERPLEXITY,
        prompt_id=prompt_id,
        prompt_text="Was ist NIS2?",
        prompt_version="v1",
        model="mock",
        target_domain="it-sicherheit.de",
        proxy_label=proxy_label,
        max_tokens=256,
        temperature=0.2,
    )


def test_mock_is_deterministic() -> None:
    eng = MockEngineAdapter(EngineId.PERPLEXITY, target_urls=TARGETS, seed=7, clock=lambda: FIXED)
    first = eng.probe(_req())
    second = eng.probe(_req())
    assert first.citations == second.citations
    assert first.target_cited == second.target_cited


def test_mock_status_usage_and_clock() -> None:
    eng = MockEngineAdapter(EngineId.CLAUDE, target_urls=TARGETS, seed=1, clock=lambda: FIXED)
    result = eng.probe(_req())
    assert result.status is ProbeStatus.OK
    assert result.engine_id is EngineId.CLAUDE
    assert result.usage.total_tokens > 0
    assert result.probed_at == FIXED


def test_mock_target_cited_matches_citations() -> None:
    eng = MockEngineAdapter(EngineId.PERPLEXITY, target_urls=TARGETS, seed=3, clock=lambda: FIXED)
    result = eng.probe(_req())
    has_target = any("it-sicherheit.de" in cite.url for cite in result.citations)
    assert result.target_cited == has_target


def test_mock_without_targets_never_cites_target() -> None:
    eng = MockEngineAdapter(EngineId.GEMINI, target_urls=(), seed=1, clock=lambda: FIXED)
    for i in range(20):
        assert eng.probe(_req(prompt_id=f"p{i}")).target_cited is False


def test_mock_forms_a_distribution_across_probes() -> None:
    eng = MockEngineAdapter(EngineId.PERPLEXITY, target_urls=TARGETS, seed=5, clock=lambda: FIXED)
    cited = sum(
        eng.probe(_req(prompt_id=f"p{i}", proxy_label=f"proxy-{i % 5}")).target_cited
        for i in range(40)
    )
    assert 0 < cited < 40


def test_boost_empty_is_byte_identical_to_baseline() -> None:
    # Sprint-4-Invariante: leerer Boost aendert die Baseline-Ziehung NICHT (Golden bleibt gruen).
    baseline = MockEngineAdapter(EngineId.PERPLEXITY, target_urls=TARGETS, seed=7)
    boosted_empty = MockEngineAdapter(
        EngineId.PERPLEXITY, target_urls=TARGETS, seed=7, boosted_urls=()
    )
    for i in range(20):
        req = _req(prompt_id=f"p{i}", proxy_label=f"proxy-{i % 5}")
        assert baseline.probe(req).citations == boosted_empty.probe(req).citations


def test_boost_forces_citation_of_patched_url() -> None:
    patched = "https://www.it-sicherheit.de/p4"  # niedrig gewichtet -> selten in der Baseline
    baseline = MockEngineAdapter(EngineId.PERPLEXITY, target_urls=TARGETS, seed=7)
    boosted = MockEngineAdapter(
        EngineId.PERPLEXITY, target_urls=TARGETS, seed=7, boosted_urls=(patched,)
    )
    base_hits = 0
    boost_hits = 0
    for i in range(20):
        req = _req(prompt_id=f"p{i}", proxy_label=f"proxy-{i % 5}")
        base_hits += any(c.url == patched for c in baseline.probe(req).citations)
        boost_hits += any(c.url == patched for c in boosted.probe(req).citations)
    assert boost_hits == 20  # jede Re-Probe zitiert die gepatchte URL garantiert
    assert base_hits < 20  # in der Baseline nicht immer -> deterministischer positiver Effekt


def test_boost_preserves_other_citations() -> None:
    # Der Boost ergaenzt nur; die uebrigen (Baseline-)Zitate bleiben erhalten.
    patched = "https://www.it-sicherheit.de/p3"
    baseline = MockEngineAdapter(EngineId.PERPLEXITY, target_urls=TARGETS, seed=2)
    boosted = MockEngineAdapter(
        EngineId.PERPLEXITY, target_urls=TARGETS, seed=2, boosted_urls=(patched,)
    )
    req = _req(prompt_id="p1", proxy_label="proxy-0")
    base_urls = {c.url for c in baseline.probe(req).citations}
    boost_urls = {c.url for c in boosted.probe(req).citations}
    assert base_urls - {patched} <= boost_urls  # nichts geht verloren
    assert patched in boost_urls
