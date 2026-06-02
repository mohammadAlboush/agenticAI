"""Composition Root: verdrahtet Adapter, Services und Flow fuer einen Sprint-1-Run.

Hier - und nur hier - werden konkrete Adapter ausgewaehlt (Mock vs. Live). Offline
nutzt durchgehend deterministische Mocks; live wird ausschliesslich Perplexity real
abgefragt (Entscheidung Sprint 1), alle anderen Engines bleiben gemockt.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from geo_audit_loop.adapters.crawl.advertools_crawler import AdvertoolsCrawlAdapter
from geo_audit_loop.adapters.crawl.mock import MockCrawlAdapter
from geo_audit_loop.adapters.engines.mock import MockEngineAdapter
from geo_audit_loop.adapters.engines.perplexity import PerplexityEngineAdapter
from geo_audit_loop.adapters.proxy.webshare import WebshareProxyPool
from geo_audit_loop.adapters.sample_data import build_sample_inventory, sample_target_urls
from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
from geo_audit_loop.agents.inventory_crawler import InventoryCrawlerService
from geo_audit_loop.agents.sampler import SamplerService
from geo_audit_loop.config import constants as c
from geo_audit_loop.config.engines import ENGINE_REGISTRY
from geo_audit_loop.config.pricing import PRICE_TABLE
from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.inventory import CrawlOptions
from geo_audit_loop.domain.probe import EngineId, EngineProbeSpec, ProbePrompt
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.orchestration.sprint1_flow import Sprint1Flow, Sprint1Pipeline
from geo_audit_loop.ports.crawl import CrawlPort
from geo_audit_loop.ports.engine import EnginePort
from geo_audit_loop.ports.proxy import ProxyPort


@dataclass(frozen=True)
class RunAssembly:
    """Alles, was ein Run braucht (vom Composition Root erstellt)."""

    flow: Sprint1Flow
    pipeline: Sprint1Pipeline
    storage: SqliteStorage
    cost_tracker: CostTracker
    run_context: RunContext


def build_specs() -> dict[EngineId, EngineProbeSpec]:
    """Baut die Pro-Engine-Probe-Spezifikationen aus der Registry."""
    return {
        engine_id: EngineProbeSpec(
            engine_id=engine_id,
            model=cfg.model,
            max_tokens=c.DEFAULT_MAX_TOKENS,
            temperature=c.DEFAULT_TEMPERATURE,
            search_mode=cfg.search_mode,
        )
        for engine_id, cfg in ENGINE_REGISTRY.items()
    }


def build_proxy(settings: Settings, *, offline: bool) -> ProxyPort:
    """Baut den Proxy-Pool (live aus der Webshare-Datei, sonst leer)."""
    if offline or not settings.proxy_file.exists():
        return WebshareProxyPool([], seed=settings.run_seed)
    return WebshareProxyPool.from_file(settings.proxy_file, seed=settings.run_seed)


def build_engines(
    settings: Settings, *, offline: bool, target_urls: Sequence[str], proxy: ProxyPort
) -> dict[EngineId, EnginePort]:
    """Waehlt je Engine den Live- oder Mock-Adapter (nur Perplexity geht live)."""
    engines: dict[EngineId, EnginePort] = {}
    for engine_id in ENGINE_REGISTRY:
        live = (not offline) and settings.is_live(engine_id) and engine_id is EngineId.PERPLEXITY
        if live:
            engines[engine_id] = PerplexityEngineAdapter(
                api_key=settings.api_key_for(engine_id), proxy=proxy
            )
        else:
            engines[engine_id] = MockEngineAdapter(
                engine_id, target_urls=target_urls, seed=settings.run_seed
            )
    return engines


def build_crawl(*, offline: bool, domain: str) -> CrawlPort:
    """Waehlt den Crawl-Adapter (offline: Mock-Inventar der Domain; live: advertools)."""
    if offline:
        return MockCrawlAdapter(build_sample_inventory(domain))
    return AdvertoolsCrawlAdapter()


def assemble_run(
    settings: Settings,
    *,
    domain: str,
    offline: bool,
    run_id: str,
    now: datetime,
    prompts: Sequence[ProbePrompt],
    prompt_version: str,
    logger: logging.Logger | None = None,
) -> RunAssembly:
    """Verdrahtet Storage, CostTracker, Engines, Services und den Flow fuer einen Run."""
    storage = SqliteStorage(settings.db_path)
    storage.initialize()
    cost_tracker = CostTracker(
        max_probes=settings.max_probes,
        max_usd=settings.max_usd,
        max_tokens=settings.max_tokens,
        price_table=PRICE_TABLE,
    )
    proxy = build_proxy(settings, offline=offline)
    target_urls = sample_target_urls(domain)
    engines = build_engines(settings, offline=offline, target_urls=target_urls, proxy=proxy)
    sampler = SamplerService(
        engines=engines,
        specs=build_specs(),
        proxy=proxy,
        storage=storage,
        cost_tracker=cost_tracker,
        n_proxy_ips=settings.n_proxy_ips,
        logger=logger,
    )
    crawler = InventoryCrawlerService(
        crawl=build_crawl(offline=offline, domain=domain), storage=storage, logger=logger
    )
    run_context = RunContext(
        run_id=run_id,
        target_domain=domain,
        started_at=now,
        seed=settings.run_seed,
        prompt_set_version=prompt_version,
        config_hash=settings.run_fingerprint(),
    )
    options = CrawlOptions(
        max_pages=c.DEFAULT_MAX_PAGES,
        download_delay_s=c.DEFAULT_DOWNLOAD_DELAY_S,
        concurrent_per_domain=c.DEFAULT_CONCURRENT_PER_DOMAIN,
        user_agent=c.DEFAULT_USER_AGENT,
    )
    pipeline = Sprint1Pipeline(
        sampler=sampler,
        crawler=crawler,
        storage=storage,
        cost_tracker=cost_tracker,
        run_context=run_context,
        prompts=prompts,
        options=options,
        top_n=settings.top_n,
        logger=logger,
    )
    return RunAssembly(
        flow=Sprint1Flow(pipeline),
        pipeline=pipeline,
        storage=storage,
        cost_tracker=cost_tracker,
        run_context=run_context,
    )
