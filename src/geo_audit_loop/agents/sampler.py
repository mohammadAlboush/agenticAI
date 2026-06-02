"""Sampler-Service: Multi-Proxy-Probing-Matrix (Pitch: 5 IPs x 4 Engines x 12 Prompts).

Deterministische Reihenfolge (Prompts wie uebergeben, Engines nach Id sortiert, IP-Slots
0..n-1). Checkpoint-faehig: bereits erledigte Probes werden uebersprungen. Budget wird vor
jeder Probe geprueft (``BudgetExceeded`` bricht den Lauf sauber ab; erledigte Probes
bleiben persistiert). Haengt nur an domain, ports und observability - nie an Adaptern.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence

from geo_audit_loop.domain.metrics import ProbeAggregate, aggregate_probes
from geo_audit_loop.domain.probe import (
    EngineId,
    EngineProbeSpec,
    ProbePrompt,
    ProbeRequest,
)
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.ports.engine import EnginePort
from geo_audit_loop.ports.proxy import ProxyPort
from geo_audit_loop.ports.storage import StoragePort

_AGENT = "sampler"


class SamplerService:
    """Baut und fuehrt die Probe-Matrix aus, persistiert und aggregiert die Ergebnisse."""

    def __init__(
        self,
        *,
        engines: Mapping[EngineId, EnginePort],
        specs: Mapping[EngineId, EngineProbeSpec],
        proxy: ProxyPort,
        storage: StoragePort,
        cost_tracker: CostTracker,
        n_proxy_ips: int,
        logger: logging.Logger | None = None,
    ) -> None:
        self._engines = dict(engines)
        self._specs = dict(specs)
        self._proxy = proxy
        self._storage = storage
        self._cost = cost_tracker
        self._n_proxy_ips = n_proxy_ips
        self._log = logger if logger is not None else logging.getLogger(__name__)

    def _engine_order(self) -> list[EngineId]:
        return sorted((e for e in self._engines if e in self._specs), key=lambda e: e.value)

    def run(self, run_context: RunContext, prompts: Sequence[ProbePrompt]) -> list[ProbeAggregate]:
        """Fuehrt die gesamte Probe-Matrix aus und liefert die Aggregate je (Engine, Prompt)."""
        for prompt in prompts:
            for engine_id in self._engine_order():
                self._probe_cell(run_context, prompt, engine_id)
        return aggregate_probes(self._storage.load_probes(run_context.run_id))

    def _probe_cell(
        self, run_context: RunContext, prompt: ProbePrompt, engine_id: EngineId
    ) -> None:
        engine = self._engines[engine_id]
        spec = self._specs[engine_id]
        for ip_index in range(self._n_proxy_ips):
            proxy_label = self._proxy.label_for(ip_index)
            if self._storage.has_probe(
                run_context.run_id, prompt.prompt_id, engine_id, proxy_label
            ):
                continue
            self._cost.ensure_can_probe()
            request = ProbeRequest(
                run_id=run_context.run_id,
                engine_id=engine_id,
                prompt_id=prompt.prompt_id,
                prompt_text=prompt.text,
                prompt_version=run_context.prompt_set_version,
                model=spec.model,
                target_domain=run_context.target_domain,
                proxy_label=proxy_label,
                proxy_index=ip_index,
                max_tokens=spec.max_tokens,
                temperature=spec.temperature,
                search_mode=spec.search_mode,
            )
            started = time.perf_counter()
            result = engine.probe(request)
            self._storage.save_probe(result)
            self._cost.record(result.model, result.usage)
            log_event(
                self._log,
                "probe.done",
                run_id=run_context.run_id,
                agent=_AGENT,
                engine=engine_id.value,
                prompt_id=prompt.prompt_id,
                proxy_label=proxy_label,
                status=result.status.value,
                target_cited=result.target_cited,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
