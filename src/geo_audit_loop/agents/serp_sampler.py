"""SERP-Sampler-Service: fragt das versionierte Keyword-Query-Set gegen den ``SerpPort`` ab.

Deterministischer Agent ohne LLM (Unit-Tests statt Eval, Projektregeln §5). Checkpoint-
faehig: bereits persistierte ``(run_id, provider, query_id)``-Zellen werden beim
Neustart uebersprungen (§6). Vor jeder Abfrage wird die Pro-Provider-Request-Quote
geprueft (``ensure_can_request``); eine erschoepfte Quote stoppt NUR die restlichen
SERP-Abfragen dieses Providers (geloggt), nie den Gesamtlauf — globale Caps setzt
der Proben-Sampler durch. Haengt nur an domain, ports und observability — nie an
Adaptern.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from geo_audit_loop.config.constants import SERP_TOP_K
from geo_audit_loop.domain.errors import BudgetExceeded
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.domain.serp import SerpProvider, SerpQuery, SerpRequest, SerpResult
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.ports.serp import SerpPort
from geo_audit_loop.ports.storage import StoragePort

_AGENT = "serp_sampler"


class SerpSamplerService:
    """Fuehrt die SERP-Abfragen aus, persistiert checkpoint-faehig und respektiert die Quote."""

    def __init__(
        self,
        *,
        serp: SerpPort,
        storage: StoragePort,
        cost_tracker: CostTracker,
        top_k: int = SERP_TOP_K,
        logger: logging.Logger | None = None,
    ) -> None:
        self._serp = serp
        self._storage = storage
        self._cost = cost_tracker
        self._top_k = top_k
        self._log = logger if logger is not None else logging.getLogger(__name__)

    @property
    def provider(self) -> SerpProvider:
        """Identitaet der verdrahteten SERP-Quelle (fuer Overlap-Provenienz und Logs)."""
        return self._serp.provider

    def run(self, run_context: RunContext, queries: Sequence[SerpQuery]) -> list[SerpResult]:
        """Fragt alle offenen Queries ab und liefert die persistierten Ergebnisse des Runs.

        Reihenfolge wie uebergeben (das Query-Set ist bereits deterministisch sortiert).
        Auch ``ERROR``-Ergebnisse werden persistiert und verbucht — ein fehlgeschlagener
        Live-Request hat die Quota trotzdem verbraucht.
        """
        provider = self._serp.provider
        for query in queries:
            if self._storage.has_serp_result(run_context.run_id, provider, query.query_id):
                continue
            try:
                self._cost.ensure_can_request(provider.value)
            except BudgetExceeded as exc:
                # Provider-Quote erschoepft: restliche Queries NUR dieses Providers
                # ueberspringen (geloggt) — der Gesamtlauf laeuft weiter.
                log_event(
                    self._log,
                    "serp.quota_exhausted",
                    run_id=run_context.run_id,
                    level=logging.WARNING,
                    agent=_AGENT,
                    provider=provider.value,
                    query_id=query.query_id,
                    limit=exc.limit,
                    used=exc.used,
                )
                break
            request = SerpRequest(run_id=run_context.run_id, query=query, top_k=self._top_k)
            started = time.perf_counter()
            result = self._serp.search(request)
            self._cost.record_request(provider.value)
            self._storage.save_serp_result(result)
            log_event(
                self._log,
                "serp.done",
                run_id=run_context.run_id,
                agent=_AGENT,
                provider=provider.value,
                query_id=query.query_id,
                status=result.status.value,
                n_entries=len(result.entries),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        return self._storage.load_serp_results(run_context.run_id, provider)
