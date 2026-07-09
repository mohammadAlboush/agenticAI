"""Composition Root: verdrahtet Adapter, Services und Flow fuer einen Sprint-1-Run.

Hier - und nur hier - werden konkrete Adapter ausgewaehlt (Mock vs. Live). Offline
nutzt durchgehend deterministische Mocks; live sind Perplexity, Gemini und ChatGPT
real abfragbar (``GEO_LIVE_ENGINES``), alle anderen Engines bleiben gemockt. Der
Live-Loop (SERP/IndexNow/WordPress) ist mehrfach ge-gated: Default off/mock, echte
Writes nur hinter Doppel-Opt-in (``GEO_ALLOW_REMOTE`` UND CLI ``--allow-remote``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from geo_audit_loop.adapters.crawl.advertools_crawler import AdvertoolsCrawlAdapter
from geo_audit_loop.adapters.crawl.mock import MockCrawlAdapter
from geo_audit_loop.adapters.engines.chatgpt import ChatGptEngineAdapter
from geo_audit_loop.adapters.engines.gemini import GeminiEngineAdapter
from geo_audit_loop.adapters.engines.mock import MockEngineAdapter
from geo_audit_loop.adapters.engines.perplexity import PerplexityEngineAdapter
from geo_audit_loop.adapters.indexing.indexnow import IndexNowAdapter
from geo_audit_loop.adapters.indexing.mock import MockIndexingAdapter
from geo_audit_loop.adapters.proxy.webshare import WebshareProxyPool
from geo_audit_loop.adapters.publisher.filesystem import FilesystemPublisher
from geo_audit_loop.adapters.publisher.mock import MockPublisher
from geo_audit_loop.adapters.publisher.wordpress import WordPressPublisher
from geo_audit_loop.adapters.reasoning.mock import MockReasoningAdapter
from geo_audit_loop.adapters.sample_data import build_sample_inventory, sample_target_urls
from geo_audit_loop.adapters.serp.mock import MockSerpAdapter
from geo_audit_loop.adapters.serp.serper import SerperSerpAdapter
from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
from geo_audit_loop.agents.effect_analyst import EffectAnalystService
from geo_audit_loop.agents.fix_agent import FixAgentService
from geo_audit_loop.agents.geo_auditor import GeoAuditorService
from geo_audit_loop.agents.inventory_crawler import InventoryCrawlerService
from geo_audit_loop.agents.pattern_miner import PatternMinerService
from geo_audit_loop.agents.sampler import SamplerService
from geo_audit_loop.agents.serp_sampler import SerpSamplerService
from geo_audit_loop.config import constants as c
from geo_audit_loop.config.engines import ENGINE_REGISTRY
from geo_audit_loop.config.pricing import PRICE_TABLE
from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.errors import ConfigError
from geo_audit_loop.domain.inventory import CrawlOptions
from geo_audit_loop.domain.probe import EngineId, EngineProbeSpec, ProbePhase, ProbePrompt
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.domain.serp import SerpProvider, SerpQuery
from geo_audit_loop.memory.mock import MockMemoryAdapter
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.orchestration.approval import ApprovalGate, AutoApproveGate
from geo_audit_loop.orchestration.sprint1_flow import Sprint1Flow, Sprint1Pipeline
from geo_audit_loop.orchestration.sprint2_flow import Sprint2Flow, Sprint2Pipeline
from geo_audit_loop.orchestration.sprint3_flow import Sprint3Flow, Sprint3Pipeline
from geo_audit_loop.orchestration.sprint4_flow import Sprint4Flow, Sprint4Pipeline
from geo_audit_loop.ports.crawl import CrawlPort
from geo_audit_loop.ports.engine import EnginePort
from geo_audit_loop.ports.indexing import IndexingPort
from geo_audit_loop.ports.memory import MemoryPort
from geo_audit_loop.ports.proxy import ProxyPort
from geo_audit_loop.ports.publisher import PublisherPort
from geo_audit_loop.ports.reasoning import ReasoningPort
from geo_audit_loop.ports.serp import SerpPort
from geo_audit_loop.prompts.loader import load_prompt, load_serp_query_set


@dataclass(frozen=True)
class RunAssembly:
    """Alles, was ein Run braucht (vom Composition Root erstellt).

    ``flow``/``pipeline`` sind je nach Modus die Sprint-1- (Messung), Sprint-2- (Lern-Loop)
    oder Sprint-3-Variante (Fix + HITL + Deploy); alle teilen die ``report``-Property.
    """

    flow: Sprint1Flow | Sprint2Flow | Sprint3Flow | Sprint4Flow
    pipeline: Sprint1Pipeline | Sprint2Pipeline | Sprint3Pipeline | Sprint4Pipeline
    storage: SqliteStorage
    cost_tracker: CostTracker
    run_context: RunContext


def build_publisher(settings: Settings, *, offline: bool) -> PublisherPort:
    """Waehlt den Deploy-Publisher: ``mock`` (Default) | ``filesystem`` | ``wordpress`` (Gate).

    Offline wird ``wordpress`` IMMER auf den ``MockPublisher`` erzwungen (analog
    ``build_indexer``/``build_serp``): schon der Dry-Run-Pfad des WP-Adapters macht echte
    Slug-Resolve-GETs — kein Netz im Offline-Pfad (Projektregeln §5/§7), auch nicht mit
    einer live-vorbereiteten ``.env``. ``wordpress`` steht zusaetzlich hinter dem
    ``GEO_ALLOW_REMOTE``-Gate: ohne explizites Opt-in wirft die Factory ``ConfigError`` —
    der Demo-/CLI-Pfad kann strukturell keinen echten externen Write ausloesen
    (Projektregeln §6). Selbst mit Gate bleibt der Adapter im Dry-Run, bis zusaetzlich
    das CLI-Flag ``--allow-remote`` gesetzt ist (Doppel-Gate in ``assemble_run``).
    """
    if settings.publisher == "wordpress":
        if offline:
            return MockPublisher()
        if not settings.allow_remote:
            raise ConfigError(
                "GEO_PUBLISHER=wordpress erfordert GEO_ALLOW_REMOTE=true (Doppel-Gate, §6)"
            )
        return WordPressPublisher(
            base_url=settings.wp_base_url,
            username=settings.wp_username,
            app_password=settings.wp_app_password,
            runs_dir=settings.runs_dir,
            allow_remote=settings.allow_remote,
        )
    if settings.publisher == "filesystem":
        return FilesystemPublisher(settings.runs_dir)
    return MockPublisher()


def build_indexer(
    settings: Settings, *, offline: bool, notify_index_cli: bool = False
) -> IndexingPort:
    """Waehlt den Index-Kanal: offline IMMER Mock; live nur mit Key UND Opt-in.

    Der Live-Adapter (IndexNow) entsteht ausschliesslich, wenn (1) nicht offline,
    (2) ``INDEXNOW_KEY`` gesetzt und (3) das Opt-in vorliegt (``GEO_NOTIFY_INDEX``
    oder CLI ``--notify-index``). In allen anderen Faellen liefert die Factory den
    ``MockIndexingAdapter`` — der offline ohnehin nie aufgerufen wird, weil
    ``build_index_submission`` bei Dry-Run-Deploys strukturell ``None`` liefert.
    """
    opt_in = settings.notify_index or notify_index_cli
    if offline or not opt_in or not settings.indexnow_key:
        return MockIndexingAdapter()
    return IndexNowAdapter(key=settings.indexnow_key, key_location=settings.indexnow_key_location)


def build_serp(settings: Settings, *, offline: bool, domain: str) -> SerpPort | None:
    """Waehlt die SERP-Quelle: ``off`` => ``None`` (exakter No-Op, Fingerprint unveraendert).

    ``mock`` liefert den seed-deterministischen Mock; ``serper`` die Live-API — offline
    wird aber IMMER auf den Mock erzwungen (kein Netz im Offline-Pfad, Projektregeln §5/§7).
    Fehlender ``SERPER_API_KEY`` im Live-Fall -> ``ConfigError`` (bei Konstruktion, nie spaeter).
    """
    if settings.serp_provider == "off":
        return None
    if offline or settings.serp_provider == "mock":
        return MockSerpAdapter(domain=domain, seed=settings.run_seed)
    return SerperSerpAdapter(api_key=settings.serper_api_key)


def build_request_limits(settings: Settings) -> dict[str, int]:
    """Pro-Provider-Request-Quoten fuer den ``CostTracker`` (zusaetzlich zu globalen Caps).

    Nur explizit begrenzte Provider erhalten einen Eintrag (Serper-Kontingent immer,
    Gemini-Free-Tier optional); alle anderen bleiben unbegrenzt — dort gelten weiterhin
    ausschliesslich die globalen Caps (max_probes/max_usd/max_tokens).
    """
    limits: dict[str, int] = {SerpProvider.SERPER.value: settings.max_requests_serper}
    if settings.max_requests_gemini is not None:
        limits[EngineId.GEMINI.value] = settings.max_requests_gemini
    return limits


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
    """Baut den Proxy-Pool (live aus der Webshare-Datei, sonst leer).

    ``proxy_file=None`` (auch via leerem ``GEO_PROXY_FILE``) bedeutet: kein Pool.
    """
    if offline or settings.proxy_file is None or not settings.proxy_file.exists():
        return WebshareProxyPool([], seed=settings.run_seed)
    return WebshareProxyPool.from_file(settings.proxy_file, seed=settings.run_seed)


def _build_perplexity(settings: Settings, proxy: ProxyPort) -> EnginePort:
    return PerplexityEngineAdapter(api_key=settings.api_key_for(EngineId.PERPLEXITY), proxy=proxy)


def _build_gemini(settings: Settings, proxy: ProxyPort) -> EnginePort:
    return GeminiEngineAdapter(api_keys=settings.api_keys_for(EngineId.GEMINI), proxy=proxy)


def _build_chatgpt(settings: Settings, proxy: ProxyPort) -> EnginePort:
    return ChatGptEngineAdapter(api_key=settings.api_key_for(EngineId.CHATGPT), proxy=proxy)


#: Engines mit Live-Adapter; alle anderen bleiben (auch im Live-Modus) gemockt.
_LIVE_ENGINE_BUILDERS: dict[EngineId, Callable[[Settings, ProxyPort], EnginePort]] = {
    EngineId.PERPLEXITY: _build_perplexity,
    EngineId.GEMINI: _build_gemini,
    EngineId.CHATGPT: _build_chatgpt,
}


def build_engines(
    settings: Settings,
    *,
    offline: bool,
    target_urls: Sequence[str],
    proxy: ProxyPort,
    boosted_urls: Sequence[str] = (),
) -> dict[EngineId, EnginePort]:
    """Waehlt je Engine den Live- oder Mock-Adapter (live: Perplexity, Gemini).

    ``boosted_urls`` (Sprint 4, nur Mock): gepatchte URLs werden in der Re-Probe garantiert
    zitiert (deterministischer Effekt); Live-Adapter ignorieren den Boost (messen die Realitaet).
    Live-faehig sind Perplexity, Gemini und ChatGPT (Responses-API mit web_search).
    """
    engines: dict[EngineId, EnginePort] = {}
    for engine_id in ENGINE_REGISTRY:
        builder = _LIVE_ENGINE_BUILDERS.get(engine_id)
        if (not offline) and settings.is_live(engine_id) and builder is not None:
            engines[engine_id] = builder(settings, proxy)
        else:
            engines[engine_id] = MockEngineAdapter(
                engine_id,
                target_urls=target_urls,
                seed=settings.run_seed,
                boosted_urls=boosted_urls,
            )
    return engines


def build_memory(settings: Settings, *, offline: bool) -> MemoryPort:
    """Waehlt das Gedaechtnis-Backend: ``mock`` (Default, deterministisch) | ``chroma`` (bge-m3).

    Offline erzwingt immer das deterministische Mock (Reproduzierbarkeit, §7). Der Chroma-Adapter
    ist opt-in (Extra ``memory``); sein Import ist lazy — der Offline-/CI-Pfad laedt ihn nie.
    """
    if offline or settings.memory_provider == "mock":
        return MockMemoryAdapter(settings.db_path)
    from geo_audit_loop.memory.chroma import ChromaMemoryAdapter

    return ChromaMemoryAdapter(
        chroma_path=settings.chroma_path, embedding_model=settings.embedding_model
    )


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
    fix: bool = False,
    learn: bool = False,
    approval_gate: ApprovalGate | None = None,
    live_crawl: bool = False,
    notify_index: bool = False,
    allow_remote: bool = False,
    logger: logging.Logger | None = None,
) -> RunAssembly:
    """Verdrahtet Storage, CostTracker, Engines, Services und den Flow fuer einen Run.

    ``explain=True`` haengt den Sprint-2-Lern-Loop (Pattern-Miner + GEO-Auditor) an die
    Sprint-1-Messung. ``fix=True`` haengt zusaetzlich den Sprint-3-Fix-/Deploy-Loop an
    (Fix-Agent + HITL-Gate + Publisher). ``learn=True`` schliesst den Sprint-4-Loop
    (Gedaechtnis-Abruf vor dem Fix + Effekt-Re-Probe danach); es impliziert ``fix`` (und damit
    ``explain``). Das HITL-Gate ist ``approval_gate`` (Default: ``AutoApproveGate``).
    ``live_crawl=True`` crawlt die Zieldomain real.

    Live-Loop: ``notify_index`` ist das CLI-Opt-in fuer die Index-Einreichung
    (zusaetzlich zu ``GEO_NOTIFY_INDEX``); ``allow_remote`` ist die CLI-Haelfte des
    Doppel-Gates fuer echte Deploys — ``deploy_dry_run=False`` gilt NUR bei
    ``GEO_ALLOW_REMOTE`` UND ``--allow-remote`` UND nicht offline (Projektregeln §6)
    UND einem interaktiven HITL-Gate: mit ``AutoApproveGate`` (``--approve-all``)
    wirft die Factory ``ConfigError`` — kein Auto-Deploy ohne menschliche Review.
    """
    fix = fix or learn
    explain = explain or fix
    storage = SqliteStorage(settings.db_path)
    storage.initialize()
    cost_tracker = CostTracker(
        # Sprint 4: Der Loop probt zweimal (Baseline + Re-Probe) -> Budget fuer beide Matrizen.
        max_probes=settings.max_probes * 2 if learn else settings.max_probes,
        max_usd=settings.max_usd,
        max_tokens=settings.max_tokens,
        price_table=PRICE_TABLE,
        request_limits=build_request_limits(settings),
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
    # Live-Loop: SERP-Messung parallel zur Baseline (off => None => exakter No-Op).
    serp_port = build_serp(settings, offline=offline, domain=domain)
    serp_sampler: SerpSamplerService | None = None
    serp_queries: tuple[SerpQuery, ...] = ()
    serp_query_set_version = ""
    if serp_port is not None:
        serp_query_set_version, loaded_queries = load_serp_query_set(
            settings.serp_query_set_version
        )
        serp_queries = tuple(loaded_queries)
        serp_sampler = SerpSamplerService(
            serp=serp_port,
            storage=storage,
            cost_tracker=cost_tracker,
            top_k=settings.serp_top_k,
            logger=logger,
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
        serp_sampler=serp_sampler,
        serp_queries=serp_queries,
        serp_query_set_version=serp_query_set_version,
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
        max_tokens=c.REASONING_MAX_TOKENS,
        storage=storage,
        logger=logger,
    )
    geo_auditor = GeoAuditorService(
        reasoning=reasoning,
        system_prompt=ga_prompt,
        prompt_version=ga_version,
        cost_tracker=cost_tracker,
        max_tokens=c.REASONING_MAX_TOKENS,
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
    if not fix:
        return RunAssembly(
            flow=Sprint2Flow(sprint2),
            pipeline=sprint2,
            storage=storage,
            cost_tracker=cost_tracker,
            run_context=run_context,
        )

    # Unter --learn nutzt der Fix-Agent den gedaechtnis-informierten Prompt v2 (sonst v1).
    fix_prompt_name = c.FIX_AGENT_LEARN_VERSION if learn else "v1"
    fx_version, fx_prompt = load_prompt("fix_agent", fix_prompt_name)
    fix_agent = FixAgentService(
        reasoning=reasoning,
        system_prompt=fx_prompt,
        prompt_version=fx_version,
        cost_tracker=cost_tracker,
        max_tokens=c.REASONING_MAX_TOKENS,
        storage=storage,
        logger=logger,
    )
    gate: ApprovalGate = approval_gate if approval_gate is not None else AutoApproveGate()
    # Doppel-Gate (Projektregeln §6): ein echter (non-dry-run) Deploy braucht BEIDE Opt-ins
    # (GEO_ALLOW_REMOTE UND CLI --allow-remote) und ist offline strukturell unmoeglich.
    deploy_dry_run = not (settings.allow_remote and allow_remote and not offline)
    if not deploy_dry_run and isinstance(gate, AutoApproveGate):
        # HITL bleibt hart (Projektregeln §6): ein echter Remote-Deploy erfordert, dass
        # ein Mensch jeden Patch sieht — Auto-Freigabe darf das Gate nie durchlaufen.
        raise ConfigError(
            "Echter Remote-Deploy erfordert eine interaktive HITL-Freigabe - "
            "--approve-all ist nicht mit --allow-remote kombinierbar (Projektregeln §6)."
        )
    sprint3 = Sprint3Pipeline(
        base=sprint2,
        fix_agent=fix_agent,
        publisher=build_publisher(settings, offline=offline),
        approval_gate=gate,
        storage=storage,
        run_context=run_context,
        indexer=build_indexer(settings, offline=offline, notify_index_cli=notify_index),
        deploy_dry_run=deploy_dry_run,
        logger=logger,
    )
    if not learn:
        return RunAssembly(
            flow=Sprint3Flow(sprint3),
            pipeline=sprint3,
            storage=storage,
            cost_tracker=cost_tracker,
            run_context=run_context,
        )

    # --- Sprint 4: geschlossener Lern-Loop (Gedaechtnis + Effekt-Re-Probe) ---
    memory = build_memory(settings, offline=offline)
    effect_analyst = EffectAnalystService(memory=memory, storage=storage, logger=logger)
    specs = build_specs()

    def build_reprobe_sampler(approved_urls: frozenset[str]) -> SamplerService:
        """Baut den Re-Probe-Sampler: geboostete Engines (gepatchte URLs) + REPROBE-Phase."""
        reprobe_engines = build_engines(
            settings,
            offline=offline,
            target_urls=target_urls,
            proxy=proxy,
            boosted_urls=tuple(sorted(approved_urls)),
        )
        return SamplerService(
            engines=reprobe_engines,
            specs=specs,
            proxy=proxy,
            storage=storage,
            cost_tracker=cost_tracker,  # geteiltes Budget: Re-Probe zaehlt mit
            n_proxy_ips=settings.n_proxy_ips,
            phase=ProbePhase.REPROBE,
            logger=logger,
        )

    sprint4 = Sprint4Pipeline(
        base=sprint3,
        memory=memory,
        effect_analyst=effect_analyst,
        build_reprobe_sampler=build_reprobe_sampler,
        prompts=prompts,
        run_context=run_context,
        logger=logger,
    )
    return RunAssembly(
        flow=Sprint4Flow(sprint4),
        pipeline=sprint4,
        storage=storage,
        cost_tracker=cost_tracker,
        run_context=run_context,
    )
