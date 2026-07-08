"""Unit: Competitive-Share-of-Voice — reine, deterministische Domaenenfunktion (kein I/O)."""

from __future__ import annotations

from datetime import datetime

from geo_audit_loop.domain.competitive import (
    ShareOfVoiceReport,
    compute_share_of_voice,
)
from geo_audit_loop.domain.probe import Citation, EngineId, ProbeResult, ProbeStatus

FIXED = datetime(2026, 1, 1, 12, 0, 0)
TARGET = "it-sicherheit.de"


def _probe(idx: int, urls: list[str], *, status: ProbeStatus = ProbeStatus.OK) -> ProbeResult:
    citations = tuple(
        Citation(url=u, engine=EngineId.GEMINI, rank=i + 1) for i, u in enumerate(urls)
    )
    return ProbeResult(
        run_id="r1",
        engine_id=EngineId.GEMINI,
        model="mock",
        prompt_id=f"p{idx}",
        prompt_version="v1",
        citations=citations,
        status=status,
        probed_at=FIXED,
    )


def _sov(probes: list[ProbeResult]) -> ShareOfVoiceReport:
    return compute_share_of_voice(probes, TARGET, run_id="r1", generated_at=FIXED)


def test_ranks_domains_by_citation_share() -> None:
    # bsi in 3 Probes, target in 2, wikipedia in 1 (von 4 OK-Probes).
    probes = [
        _probe(0, ["https://www.bsi.bund.de/a", "https://www.it-sicherheit.de/x"]),
        _probe(1, ["https://www.bsi.bund.de/b"]),
        _probe(2, ["https://www.bsi.bund.de/c", "https://de.wikipedia.org/wiki/IT"]),
        _probe(3, ["https://www.it-sicherheit.de/y"]),
    ]
    report = _sov(probes)
    assert report.n_probes == 4
    assert [(s.domain, s.citation_count) for s in report.shares] == [
        ("bsi.bund.de", 3),
        ("it-sicherheit.de", 2),
        ("de.wikipedia.org", 1),
    ]
    assert [s.rank for s in report.shares] == [1, 2, 3]  # 1-basierter Rang
    bsi = report.shares[0]
    assert bsi.citation_rate == 0.75 and bsi.is_target is False
    # Zieldomain markiert, Rang + Share korrekt.
    target = next(s for s in report.shares if s.is_target)
    assert target.domain == "it-sicherheit.de"
    assert report.target_rank == 2
    assert report.target_share == 0.5


def test_dedups_per_probe() -> None:
    # bsi zweimal in EINER Antwort -> zaehlt einmal (Anteil der Antworten, nicht der Zitate).
    probes = [_probe(0, ["https://www.bsi.bund.de/a", "https://www.bsi.bund.de/b"])]
    report = _sov(probes)
    assert report.n_probes == 1
    bsi = next(s for s in report.shares if s.domain == "bsi.bund.de")
    assert bsi.citation_count == 1
    assert bsi.citation_rate == 1.0


def test_error_probes_excluded_from_denominator() -> None:
    probes = [
        _probe(0, ["https://www.bsi.bund.de/a"]),
        _probe(1, ["https://www.bsi.bund.de/b"], status=ProbeStatus.ERROR),  # zaehlt nicht
    ]
    report = _sov(probes)
    assert report.n_probes == 1
    assert report.shares[0].citation_rate == 1.0


def test_top_competitor_pages_exclude_target_and_rank() -> None:
    probes = [
        _probe(0, ["https://www.bsi.bund.de/grundschutz", "https://www.it-sicherheit.de/x"]),
        _probe(1, ["https://www.bsi.bund.de/grundschutz"]),  # dieselbe Seite -> Count 2
        _probe(2, ["https://www.heise.de/security"]),
    ]
    report = _sov(probes)
    pages = report.top_competitor_pages
    assert [(p.url, p.citation_count) for p in pages] == [
        ("https://www.bsi.bund.de/grundschutz", 2),
        ("https://www.heise.de/security", 1),
    ]
    # keine Ziel-Seite unter den Wettbewerber-Seiten
    assert all(p.domain != "it-sicherheit.de" for p in pages)


def test_empty_and_deterministic() -> None:
    empty = _sov([])
    assert empty.n_probes == 0 and empty.shares == () and empty.target_rank is None
    probes = [
        _probe(0, ["https://www.bsi.bund.de/a", "https://de.wikipedia.org/x"]),
        _probe(1, ["https://de.wikipedia.org/y", "https://www.bsi.bund.de/b"]),
    ]
    # Eingabe-Reihenfolge egal -> identischer Report (deterministisch, totaler Ordnungsschluessel).
    assert _sov(probes) == _sov(list(reversed(probes)))


def test_representative_url_is_order_independent() -> None:
    # Zwei Schreibweisen derselben Seite (www / Trailing-Slash) kollabieren zu einem Key.
    # Die Anzeige-URL muss die lexikografisch kleinste sein — unabhaengig von der Reihenfolge.
    a = _probe(0, ["https://www.comp.com/a"])
    b = _probe(1, ["https://comp.com/a/"])
    fwd = compute_share_of_voice([a, b], TARGET, run_id="r1", generated_at=FIXED)
    rev = compute_share_of_voice([b, a], TARGET, run_id="r1", generated_at=FIXED)
    assert fwd == rev  # kein first-seen-Effekt mehr
    assert fwd.top_competitor_pages[0].url == "https://comp.com/a/"  # min der beiden Roh-URLs
    assert fwd.top_competitor_pages[0].citation_count == 2  # eine Seite ueber zwei Antworten


def test_target_beyond_top_domains_is_kept_with_true_rank() -> None:
    # comp1 (3x), comp2 (2x), Zieldomain (1x) -> Ziel rankt #3; bei top_domains=2 muss es
    # dennoch in ``shares`` erscheinen (Invariante: genau eine Ziel-Zeile), mit wahrem Rang.
    probes = (
        [_probe(i, ["https://comp1.com/x"]) for i in range(3)]
        + [_probe(10 + i, ["https://comp2.com/y"]) for i in range(2)]
        + [_probe(20, ["https://www.it-sicherheit.de/z"])]
    )
    report = compute_share_of_voice(
        probes, TARGET, run_id="r1", generated_at=FIXED, top_domains=2
    )
    assert report.target_rank == 3
    assert sum(1 for s in report.shares if s.is_target) == 1  # Invariante gewahrt trotz Kappung
    target = next(s for s in report.shares if s.is_target)
    assert target.rank == 3 and target.domain == "it-sicherheit.de"
    # Top-2-Wettbewerber + die angehaengte Zieldomain.
    assert [s.rank for s in report.shares] == [1, 2, 3]


def test_roundtrip() -> None:
    report = _sov([_probe(0, ["https://www.bsi.bund.de/a"])])
    assert ShareOfVoiceReport.model_validate_json(report.model_dump_json()) == report
