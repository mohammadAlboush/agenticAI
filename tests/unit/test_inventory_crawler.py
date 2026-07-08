"""Phase-7-Gate: Inventory-Crawler joint Crawl + Sampler-Daten zu Top/Flop."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from geo_audit_loop.adapters.crawl.mock import MockCrawlAdapter
from geo_audit_loop.adapters.sample_data import build_sample_inventory
from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
from geo_audit_loop.agents.inventory_crawler import InventoryCrawlerService
from geo_audit_loop.domain.findings import VisibilityBand, classify_band
from geo_audit_loop.domain.inventory import CrawlOptions
from geo_audit_loop.domain.metrics import evaluate_target
from geo_audit_loop.domain.probe import (
    Citation,
    EngineId,
    ProbePhase,
    ProbeResult,
    ProbeStatus,
)
from geo_audit_loop.domain.run import RunContext

FIXED = datetime(2026, 1, 1, 12, 0, 0)
TARGET = "it-sicherheit.de"
PAGES = build_sample_inventory()


def _probe(idx: int, url: str | None, phase: ProbePhase = ProbePhase.BASELINE) -> ProbeResult:
    cites = (Citation(url=url, engine=EngineId.PERPLEXITY, rank=1),) if url else ()
    cited, rank = evaluate_target(cites, TARGET)
    return ProbeResult(
        run_id="run-1",
        engine_id=EngineId.PERPLEXITY,
        model="m",
        prompt_id=f"p{idx}",
        prompt_version="v1",
        proxy_label=f"proxy-{idx}",
        citations=cites,
        target_cited=cited,
        target_rank=rank,
        status=ProbeStatus.OK,
        probed_at=FIXED,
        phase=phase,
    )


def _ctx() -> RunContext:
    return RunContext(
        run_id="run-1",
        target_domain=TARGET,
        started_at=FIXED,
        seed=42,
        prompt_set_version="v1",
        config_hash="h",
    )


def _storage_with_probes(tmp_path: Path) -> SqliteStorage:
    storage = SqliteStorage(tmp_path / "db.sqlite")
    storage.initialize()
    idx = 0
    plan = ((PAGES[0].page.url, 5), (PAGES[1].page.url, 2), ("https://other.com/x", 3))
    for url, repeats in plan:
        for _ in range(repeats):
            storage.save_probe(_probe(idx, url))
            idx += 1
    return storage


def test_top_flop_ordering_and_persistence(tmp_path: Path) -> None:
    storage = _storage_with_probes(tmp_path)
    service = InventoryCrawlerService(
        crawl=MockCrawlAdapter(PAGES), storage=storage, clock=lambda: FIXED
    )
    report = service.run(_ctx(), CrawlOptions(user_agent="t"), aggregates=[], top_n=3)

    assert report.n_pages == len(PAGES)
    assert report.n_probes == 10  # 5 + 2 + 3 OK-Probes
    assert report.top[0].url == PAGES[0].page.url
    assert report.top[0].citation_count == 5
    assert report.top[1].url == PAGES[1].page.url
    assert report.top[1].citation_count == 2
    # Flop = am wenigsten zitierte gecrawlte Seiten (hier 0 Zitate)
    assert all(entry.citation_count == 0 for entry in report.flop)
    # persistiert
    assert storage.load_report("run-1") == report
    assert len(storage.load_pages("run-1")) == len(PAGES)


def test_topflop_ignores_reprobe_phase(tmp_path: Path) -> None:
    # Regression (Sprint 4): existieren geboostete REPROBE-Probes unter derselben run_id
    # (fortgesetzter --learn-Lauf), darf der Top/Flop-Report NUR die Baseline zaehlen.
    storage = _storage_with_probes(tmp_path)  # 10 Baseline-Probes
    # Eine Flop-Seite bekommt zusaetzlich viele geboostete REPROBE-Zitate:
    flop_url = PAGES[2].page.url
    for i in range(8):
        storage.save_probe(_probe(100 + i, flop_url, phase=ProbePhase.REPROBE))
    service = InventoryCrawlerService(
        crawl=MockCrawlAdapter(PAGES), storage=storage, clock=lambda: FIXED
    )
    report = service.run(_ctx(), CrawlOptions(user_agent="t"), aggregates=[], top_n=3)
    assert report.n_probes == 10  # Baseline unveraendert (nicht 18)
    assert report.top[0].url == PAGES[0].page.url  # Ranking unveraendert durch die Re-Probe
    # PAGES[2] hatte in der Baseline 0 Zitate -> bleibt Flop, trotz REPROBE-Boost.
    top_urls = {entry.url for entry in report.top}
    assert flop_url not in top_urls


def test_pages_without_probes_score_zero(tmp_path: Path) -> None:
    storage = SqliteStorage(tmp_path / "db.sqlite")
    storage.initialize()
    service = InventoryCrawlerService(
        crawl=MockCrawlAdapter(PAGES), storage=storage, clock=lambda: FIXED
    )
    report = service.run(_ctx(), CrawlOptions(user_agent="t"), aggregates=[], top_n=5)
    assert report.n_probes == 0
    assert all(entry.citation_count == 0 for entry in report.top)
    assert all(entry.citation_rate == 0.0 for entry in report.top)
    # Ohne Probes ist jede Rate maximal unsicher (Wilson[0,0] = [0,1]) und nicht abgesetzt.
    assert all(entry.rate_ci_low == 0.0 and entry.rate_ci_high == 1.0 for entry in report.top)
    assert all(entry.band is VisibilityBand.TYPICAL for entry in report.top)
    assert report.field_citation_rate == 0.0


def test_classify_band_separates_by_confidence_interval() -> None:
    # KI ganz ueber dem Schnitt -> belastbar top; ganz darunter -> belastbar flop; sonst Rauschen.
    assert classify_band(0.30, 0.50, 0.10) is VisibilityBand.ABOVE_FIELD
    assert classify_band(0.02, 0.08, 0.20) is VisibilityBand.BELOW_FIELD
    assert classify_band(0.05, 0.40, 0.20) is VisibilityBand.TYPICAL  # KI umschliesst den Schnitt


def test_topflop_entries_carry_wilson_ci_and_band(tmp_path: Path) -> None:
    storage = _storage_with_probes(tmp_path)  # PAGES[0]=5/10, PAGES[1]=2/10, Rest 0; n=10
    service = InventoryCrawlerService(
        crawl=MockCrawlAdapter(PAGES), storage=storage, clock=lambda: FIXED
    )
    report = service.run(_ctx(), CrawlOptions(user_agent="t"), aggregates=[], top_n=8)

    # Domain-Schnitt = Mittel der Raten ueber alle 8 Seiten = (0.5 + 0.2) / 8.
    assert report.field_citation_rate == round((0.5 + 0.2) / 8, 6)
    # Jede Zeile traegt ein Wilson-KI, das ihre Rate enthaelt.
    for entry in (*report.top, *report.flop):
        assert entry.rate_ci_low <= entry.citation_rate <= entry.rate_ci_high
    # Die klar zitierte Top-Seite ist statistisch abgesetzt (KI-Untergrenze ueber dem Schnitt).
    assert report.top[0].url == PAGES[0].page.url
    assert report.top[0].band is VisibilityBand.ABOVE_FIELD
    # Bei nur n=10 ist eine 0-Zitat-Seite NICHT belastbar unter dem (niedrigen) Schnitt -> Rauschen.
    assert report.flop[0].citation_count == 0
    assert report.flop[0].band is VisibilityBand.TYPICAL
    # KI/Band ueberleben die Persistenz-Roundtrip.
    assert storage.load_report("run-1") == report


def test_saves_share_of_voice_with_target_marked(tmp_path: Path) -> None:
    # Session 3: der Crawler leitet aus denselben Baseline-Probes den SoV-Report ab + speichert ihn.
    # Probes zitieren it-sicherheit.de (PAGES[0]=5, PAGES[1]=2 -> 7 Antworten) und other.com (3).
    storage = _storage_with_probes(tmp_path)
    service = InventoryCrawlerService(
        crawl=MockCrawlAdapter(PAGES), storage=storage, clock=lambda: FIXED
    )
    service.run(_ctx(), CrawlOptions(user_agent="t"), aggregates=[], top_n=3)

    sov = storage.load_sov_report("run-1")
    assert sov is not None
    assert sov.n_probes == 10
    # Zieldomain zuerst (7/10), other.com als Wettbewerber (3/10).
    assert sov.shares[0].domain == TARGET and sov.shares[0].is_target is True
    assert sov.shares[0].citation_count == 7 and sov.shares[0].citation_rate == 0.7
    assert sov.target_rank == 1
    competitors = {s.domain for s in sov.shares if not s.is_target}
    assert "other.com" in competitors
    # Wettbewerber-Seiten enthalten die externe Seite, keine Ziel-Seite.
    assert any(p.domain == "other.com" for p in sov.top_competitor_pages)
    assert all(p.domain != TARGET for p in sov.top_competitor_pages)
