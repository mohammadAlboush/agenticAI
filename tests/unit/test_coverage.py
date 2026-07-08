"""Unit: Query-Intent-Coverage — reine, deterministische Domaenenfunktion (Session 4)."""

from __future__ import annotations

from datetime import datetime

from geo_audit_loop.domain.coverage import compute_coverage
from geo_audit_loop.domain.probe import (
    EngineId,
    ProbePrompt,
    ProbeResult,
    ProbeStatus,
    QueryIntent,
)

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _prompt(prompt_id: str, intent: QueryIntent | None) -> ProbePrompt:
    return ProbePrompt(prompt_id=prompt_id, text=f"Frage {prompt_id}?", intent=intent)


def _probe(
    prompt_id: str,
    *,
    cited: bool,
    status: ProbeStatus = ProbeStatus.OK,
) -> ProbeResult:
    return ProbeResult(
        run_id="run-1",
        engine_id=EngineId.PERPLEXITY,
        model="m",
        prompt_id=prompt_id,
        prompt_version="v1",
        target_cited=cited,
        status=status,
        probed_at=FIXED,
    )


def test_coverage_aggregates_breadth_and_depth() -> None:
    prompts = [
        _prompt("p1", QueryIntent.HOWTO),
        _prompt("p2", QueryIntent.HOWTO),
        _prompt("p3", QueryIntent.DEFINITION),
    ]
    probes = [
        _probe("p1", cited=True),
        _probe("p1", cited=False),  # p1-Rate = 0.5, abgedeckt
        _probe("p2", cited=False),
        _probe("p2", cited=False),  # p2-Rate = 0.0, nicht abgedeckt
        _probe("p3", cited=True),  # p3-Rate = 1.0, abgedeckt
    ]
    report = compute_coverage(
        prompts, probes, "it-sicherheit.de", run_id="run-1", generated_at=FIXED
    )

    by_intent = {cov.intent: cov for cov in report.intents}
    howto = by_intent[QueryIntent.HOWTO]
    assert howto.n_prompts == 2
    assert howto.n_covered == 1
    assert howto.coverage_rate == 0.5
    assert howto.mean_citation_rate == 0.25  # mean(0.5, 0.0)
    definition = by_intent[QueryIntent.DEFINITION]
    assert definition.coverage_rate == 1.0
    assert definition.mean_citation_rate == 1.0
    assert report.overall_citation_rate == 0.5  # mean(0.5, 0.0, 1.0)
    assert report.n_probes == 5


def test_prompts_without_intent_are_ignored() -> None:
    prompts = [_prompt("p1", QueryIntent.HOWTO), _prompt("p2", None)]
    probes = [_probe("p1", cited=True), _probe("p2", cited=True)]
    report = compute_coverage(
        prompts, probes, "it-sicherheit.de", run_id="run-1", generated_at=FIXED
    )
    assert {cov.intent for cov in report.intents} == {QueryIntent.HOWTO}
    # p2 (ohne Intent) darf die Gesamtrate nicht beeinflussen.
    assert report.overall_citation_rate == 1.0


def test_error_probes_are_excluded() -> None:
    prompts = [_prompt("p1", QueryIntent.HOWTO)]
    probes = [_probe("p1", cited=True, status=ProbeStatus.ERROR)]
    report = compute_coverage(
        prompts, probes, "it-sicherheit.de", run_id="run-1", generated_at=FIXED
    )
    assert report.n_probes == 0
    howto = report.intents[0]
    assert howto.n_covered == 0
    assert howto.coverage_rate == 0.0  # keine OK-Probe -> Rate 0


def test_weakest_intents_flag_blind_spots() -> None:
    prompts = [
        _prompt("p1", QueryIntent.HOWTO),
        _prompt("p2", QueryIntent.HOWTO),
        _prompt("p3", QueryIntent.HOWTO),  # coverage 1/3 ~ 0.333 < 0.5
        _prompt("p4", QueryIntent.DEFINITION),  # coverage 1/1 = 1.0 >= 0.5
    ]
    probes = [
        _probe("p1", cited=True),
        _probe("p2", cited=False),
        _probe("p3", cited=False),
        _probe("p4", cited=True),
    ]
    report = compute_coverage(
        prompts, probes, "it-sicherheit.de", run_id="run-1", generated_at=FIXED
    )
    assert report.weakest_intents == (QueryIntent.HOWTO,)
    # Schwaechster zuerst: HOWTO (0.333) vor DEFINITION (1.0).
    assert report.intents[0].intent is QueryIntent.HOWTO


def test_sort_is_total_order_and_rates_rounded() -> None:
    # Zwei Intents mit identischer coverage_rate (0.0) und mean (0.0): Tie-Break ueber intent.value.
    prompts = [
        _prompt("p1", QueryIntent.TROUBLESHOOTING),
        _prompt("p2", QueryIntent.CHECKLIST),
        _prompt("p3", QueryIntent.HOWTO),  # 1/3 -> 0.333333 (Rundung auf 6 Stellen)
        _prompt("p4", QueryIntent.HOWTO),
        _prompt("p5", QueryIntent.HOWTO),
    ]
    probes = [
        _probe("p1", cited=False),
        _probe("p2", cited=False),
        _probe("p3", cited=True),
        _probe("p4", cited=False),
        _probe("p5", cited=False),
    ]
    report = compute_coverage(
        prompts, probes, "it-sicherheit.de", run_id="run-1", generated_at=FIXED
    )
    order = [cov.intent for cov in report.intents]
    # checklist (0.0) < troubleshooting (0.0) alphabetisch, danach howto (0.333).
    assert order == [QueryIntent.CHECKLIST, QueryIntent.TROUBLESHOOTING, QueryIntent.HOWTO]
    howto = report.intents[2]
    assert howto.coverage_rate == round(1 / 3, 6)


def test_determinism_same_inputs_same_report() -> None:
    prompts = [_prompt("p1", QueryIntent.HOWTO), _prompt("p2", QueryIntent.DEFINITION)]
    probes = [_probe("p1", cited=True), _probe("p2", cited=False)]
    a = compute_coverage(prompts, probes, "d", run_id="run-1", generated_at=FIXED)
    b = compute_coverage(prompts, probes, "d", run_id="run-1", generated_at=FIXED)
    assert a == b
