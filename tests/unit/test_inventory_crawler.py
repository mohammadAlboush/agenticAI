"""Phase-7-Gate: Inventory-Crawler joint Crawl + Sampler-Daten zu Top/Flop."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from geo_audit_loop.adapters.crawl.mock import MockCrawlAdapter
from geo_audit_loop.adapters.sample_data import build_sample_inventory
from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
from geo_audit_loop.agents.inventory_crawler import InventoryCrawlerService
from geo_audit_loop.domain.inventory import CrawlOptions
from geo_audit_loop.domain.metrics import evaluate_target
from geo_audit_loop.domain.probe import Citation, EngineId, ProbeResult, ProbeStatus
from geo_audit_loop.domain.run import RunContext

FIXED = datetime(2026, 1, 1, 12, 0, 0)
TARGET = "it-sicherheit.de"
PAGES = build_sample_inventory()


def _probe(idx: int, url: str | None) -> ProbeResult:
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
