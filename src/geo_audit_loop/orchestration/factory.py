"""Composition Root: verdrahtet Adapter, Services und Flow fuer einen Sprint-1-Run.

Hier - und nur hier - werden konkrete Adapter ausgewaehlt (Mock vs. Live). Offline
nutzt durchgehend deterministische Mocks; live wird ausschliesslich Perplexity real
abgefragt (Entscheidung Sprint 1), alle anderen Engines bleiben gemockt.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from geo_audit_loop.adapters.crawl.advertools_crawler import AdvertoolsCrawlAdapter
from geo_audit_loop.adapters.crawl.mock import MockCrawlAdapter
from geo_audit_loop.adapters.engines.gemini import GeminiEngineAdapter
from geo_audit_loop.adapters.engines.mock import MockEngineAdapter
from geo_audit_loop.adapters.engines.perplexity import PerplexityEngineAdapter
from geo_audit_loop.adapters.proxy.webshare import WebshareProxyPool
from geo_audit_loop.adapters.reasoning.mock import MockReasoningAdapter
from geo_audit_loop.adapters.sample_data import build_sample_inventory, sample_target_urls
from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
from geo_audit_loop.agents.geo_auditor import GeoAuditorService
from geo_audit_loop.agents.inventory_crawler import InventoryCrawlerService
from geo_audit_loop.agents.pattern_miner import PatternMinerService
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
from geo_audit_loop.orchestration.sprint2_flow import Sprint2Flow, Sprint2Pipeline
from geo_audit_loop.ports.crawl import CrawlPort
from geo_audit_loop.ports.engine import EnginePort
from geo_audit_loop.ports.proxy import ProxyPort
from geo_audit_loop.ports.reasoning import ReasoningPort
from geo_audit_loop.prompts.loader import load_prompt


@dataclass(frozen=True)
class RunAssembly:
    """Alles, was ein Run braucht (vom Composition Root erstellt).

    ``flow``/``pipeline`` sind je nach Modus die Sprint-1- (Messung) oder die
    Sprint-2-Variante (Messung + Lern-Loop); beide teilen die ``report``-Property.
    """

    flow: Sprint1Flow | Sprint2Flow
    pipeline: Sprint1Pipeline | Sprint2Pipeline
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


def _build_perplexity(settings: Settings, proxy: ProxyPort) -> EnginePort:
    return PerplexityEngineAdapter(api_key=settings.api_key_for(EngineId.PERPLEXITY), proxy=proxy)


def _build_gemini(settings: Settings, proxy: ProxyPort) -> EnginePort:
    return GeminiEngineAdapter(api_keys=settings.api_keys_for(EngineId.GEMINI), proxy=proxy)


#: Engines mit Live-Adapter; alle anderen bleiben (auch im Live-Modus) gemockt.
_LIVE_ENGINE_BUILDERS: dict[EngineId, Callable[[Settings, ProxyPort], EnginePort]] = {
    EngineId.PERPLEXITY: _build_perplexity,
    EngineId.GEMINI: _build_gemini,
}


def build_engines(
    settings: Settings, *, offline: bool, target_urls: Sequence[str], proxy: ProxyPort
) -> dict[EngineId, EnginePort]:
    """Waehlt je Engine den Live- oder Mock-Adapter (live: Perplexity, Gemini)."""
    engines: dict[EngineId, EnginePort] = {}
    for engine_id in ENGINE_REGISTRY:
        builder = _LIVE_ENGINE_BUILDERS.get(engine_id)
        if (not offline) and settings.is_live(engine_id) and builder is not None:
            engines[engine_id] = builder(settings, proxy)
        else:
            engines[engine_id] = MockEngineAdapter(
                engine_id, target_urls=target_urls, seed=settings.run_seed
            )
    return engines


def build_crawl(*, offline: bool, domain: str, live_crawl: bool = False) -> CrawlPort:
    """Waehlt den Crawl-Adapter.

    Der echte advertools-Crawl der Zieldomain ist langsam/fragil (Timeout-Risiko) und fuer
    die Zitations-Messung nicht noetig. Er laeuft daher NUR bei ``live_crawl=True``; sonst
    (auch bei Live-Engines) liefert das deterministische Sample-Inventar der Domain die
    Wissensbasis fuer die Lern-Agenten — schnell und reproduzierbar.
    """
    if offline or not live_crawl:
        return MockCrawlAdapter(build_sample_inventory(domain))
    return AdvertoolsCrawlAdapter()


def build_reasoning(settings: Settings, *, offline: bool) -> ReasoningPort:
    """Waehlt den Reasoning-Adapter: ``mock`` (Default) | ``saia`` (Hochschule) | ``claude``.

    Der Provider ist bewusst UNABHAENGIG vom Engine-Offline-Modus waehlbar (Misch-Lauf:
    Mock-Engines + echtes Reasoning). Rueckwaertskompatibilitaet: ``GEO_LIVE_ENGINES=claude``
    wirkt im Live-Modus weiter wie ``GEO_REASONING_PROVIDER=claude``. Die SDK-Imports
    bleiben in den Live-Zweigen (Offline-Runs laden sie nicht).
    """
    provider = settings.reasoning_provider
    if provider == "mock" and not offline and settings.is_live(EngineId.CLAUDE):
        provider = "claude"
    if provider == "saia":
        from geo_audit_loop.adapters.reasoning.saia import SaiaReasoningAdapter

        return SaiaReasoningAdapter(
            api_key=settings.saia_api_key,
            base_url=settings.saia_base_url,
            model=settings.saia_model,
        )
    if provider == "claude":
        from geo_audit_loop.adapters.reasoning.claude import ClaudeReasoningAdapter

        cfg = ENGINE_REGISTRY[EngineId.CLAUDE]
        return ClaudeReasoningAdapter(
            api_key=settings.api_key_for(EngineId.CLAUDE), model=cfg.model
        )
    return MockReasoningAdapter()


def assemble_run(
    settings: Settings,
    *,
    domain: str,
    offline: bool,
    run_id: str,
    now: datetime,
    prompts: Sequence[ProbePrompt],
    prompt_version: str,
    explain: bool = False,
    live_crawl: bool = False,
    logger: logging.Logger | None = None,
) -> RunAssembly:
    """Verdrahtet Storage, CostTracker, Engines, Services und den Flow fuer einen Run.

    ``explain=True`` haengt den Sprint-2-Lern-Loop (Pattern-Miner + GEO-Auditor) an die
    Sprint-1-Messung; sonst laeuft der reine Sprint-1-Flow. ``live_crawl=True`` crawlt die
    Zieldomain real (advertools) statt das schnelle Sample-Inventar zu nutzen.
    """
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
        crawl=build_crawl(offline=offline, domain=domain, live_crawl=live_crawl),
        storage=storage,
        logger=logger,
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
    if not explain:
        return RunAssembly(
            flow=Sprint1Flow(pipeline),
            pipeline=pipeline,
            storage=storage,
            cost_tracker=cost_tracker,
            run_context=run_context,
        )

    reasoning = build_reasoning(settings, offline=offline)
    pm_version, pm_prompt = load_prompt("pattern_miner")
    ga_version, ga_prompt = load_prompt("geo_auditor")
    pattern_miner = PatternMinerService(
        reasoning=reasoning,
        system_prompt=pm_prompt,
        prompt_version=pm_version,
        cost_tracker=cost_tracker,
        storage=storage,
        logger=logger,
    )
    geo_auditor = GeoAuditorService(
        reasoning=reasoning,
        system_prompt=ga_prompt,
        prompt_version=ga_version,
        cost_tracker=cost_tracker,
        storage=storage,
        logger=logger,
    )
    sprint2 = Sprint2Pipeline(
        base=pipeline,
        pattern_miner=pattern_miner,
        geo_auditor=geo_auditor,
        storage=storage,
        run_context=run_context,
        logger=logger,
    )
    return RunAssembly(
        flow=Sprint2Flow(sprint2),
        pipeline=sprint2,
        storage=storage,
        cost_tracker=cost_tracker,
        run_context=run_context,
    )
