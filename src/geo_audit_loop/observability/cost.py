"""Kosten-Tracking und harter Budget-Cap pro Run (Projektregeln §6).

Trennung: die Engine-Adapter kennen kein Budget; der Sampler ruft vor jeder Probe
``ensure_can_probe()`` und nach jeder Probe ``record()``. Wird ein Limit erreicht,
bricht der naechste ``ensure_can_probe()`` mit ``BudgetExceeded`` sauber ab.

Zusaetzlich zu den globalen Caps (Probes/Tokens/USD) gibt es Pro-Provider-
Request-Quoten (``request_limits``, z.B. Gemini-Free-Tier oder Serper-Kontingent):
``ensure_can_request(provider)`` prueft, ``record_request(provider)`` verbucht.
Eine erreichte Provider-Quote traegt ``provider`` am ``BudgetExceeded`` — der
Aufrufer kann dann NUR diesen Provider ueberspringen statt den Run abzubrechen.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field

from geo_audit_loop.config.pricing import DEFAULT_PRICE, Price
from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.errors import BudgetExceeded
from geo_audit_loop.domain.probe import ProbeUsage


class CostSnapshot(FrozenModel):
    """Aggregierter Verbrauch eines Runs."""

    probes: int
    total_tokens: int
    total_usd: float
    requests_by_provider: dict[str, int] = Field(default_factory=dict)


class CostTracker:
    """Zaehlt Probes, Tokens, USD-Kosten und Provider-Requests; erzwingt die harten Limits."""

    def __init__(
        self,
        *,
        max_probes: int,
        max_usd: float,
        max_tokens: int,
        price_table: dict[str, Price] | None = None,
        request_limits: Mapping[str, int] | None = None,
    ) -> None:
        self._max_probes = max_probes
        self._max_usd = max_usd
        self._max_tokens = max_tokens
        self._prices = price_table if price_table is not None else {}
        self._request_limits = dict(request_limits) if request_limits is not None else {}
        self._probes = 0
        self._tokens = 0
        self._usd = 0.0
        self._requests: dict[str, int] = {}

    def ensure_can_probe(self, provider: str | None = None) -> None:
        """Wirft ``BudgetExceeded``, falls ein Limit erreicht ist (harter Cap, einheitlich ``>=``).

        Alle drei Limits werden konsistent als "weitermachen nur, solange strikt unter dem
        Cap" geprueft: ein Lauf startet keine Probe, sobald Probes, Tokens oder USD das
        jeweilige Limit erreichen (Projektregeln §6). Mit ``provider`` wird zusaetzlich
        dessen Request-Quote geprueft (``ensure_can_request``).
        """
        if self._probes >= self._max_probes:
            raise BudgetExceeded(
                "Probe-Limit erreicht",
                limit_name="max_probes",
                limit=self._max_probes,
                used=self._probes,
            )
        if self._tokens >= self._max_tokens:
            raise BudgetExceeded(
                "Token-Limit erreicht",
                limit_name="max_tokens",
                limit=self._max_tokens,
                used=self._tokens,
            )
        if self._usd >= self._max_usd:
            raise BudgetExceeded(
                "USD-Limit erreicht",
                limit_name="max_usd",
                limit=self._max_usd,
                used=self._usd,
            )
        if provider is not None:
            self.ensure_can_request(provider)

    def ensure_can_request(self, provider: str) -> None:
        """Wirft ``BudgetExceeded`` (mit ``provider``-Attribut) bei erreichter Provider-Quote.

        Provider ohne Eintrag in ``request_limits`` haben keine Quote — nur die
        globalen Caps gelten. Gleiche ``>=``-Semantik wie ``ensure_can_probe``.
        """
        limit = self._request_limits.get(provider)
        if limit is None:
            return
        used = self._requests.get(provider, 0)
        if used >= limit:
            raise BudgetExceeded(
                f"Request-Limit fuer Provider '{provider}' erreicht",
                limit_name=f"max_requests_{provider}",
                limit=limit,
                used=used,
                provider=provider,
            )

    def record_request(self, provider: str) -> None:
        """Verbucht einen ausgefuehrten Request des Providers (speist die Quote)."""
        self._requests[provider] = self._requests.get(provider, 0) + 1

    def estimate_cost(self, model: str, usage: ProbeUsage) -> float:
        """Schaetzt die USD-Kosten einer Probe anhand der Preis-Tabelle."""
        price = self._prices.get(model, DEFAULT_PRICE)
        cost = usage.prompt_tokens / 1_000_000 * price.usd_per_1m_input
        cost += usage.completion_tokens / 1_000_000 * price.usd_per_1m_output
        cost += (usage.server_search_requests or 0) * price.usd_per_search
        return cost

    def record(self, model: str, usage: ProbeUsage) -> float:
        """Verbucht eine ausgefuehrte Probe und liefert ihre geschaetzten Kosten."""
        self._probes += 1
        self._tokens += usage.total_tokens
        cost = self.estimate_cost(model, usage)
        self._usd += cost
        return cost

    def ensure_within_budget(self) -> None:
        """Wirft ``BudgetExceeded`` bei erreichtem Token-/USD-Limit (Reasoning-Schritte, §6).

        Wie ``ensure_can_probe``, aber ohne Probe-Limit: Reasoning-Aufrufe (Pattern-Miner,
        GEO-Auditor) sind keine Probes, unterliegen aber demselben Token-/Kosten-Cap.
        """
        if self._tokens >= self._max_tokens:
            raise BudgetExceeded(
                "Token-Limit erreicht",
                limit_name="max_tokens",
                limit=self._max_tokens,
                used=self._tokens,
            )
        if self._usd >= self._max_usd:
            raise BudgetExceeded(
                "USD-Limit erreicht", limit_name="max_usd", limit=self._max_usd, used=self._usd
            )

    def record_reasoning(self, model: str, usage: ProbeUsage) -> float:
        """Verbucht einen Reasoning-Aufruf (Tokens + USD, KEIN Probe-Zaehler) und liefert Kosten."""
        self._tokens += usage.total_tokens
        cost = self.estimate_cost(model, usage)
        self._usd += cost
        return cost

    @property
    def probes(self) -> int:
        """Anzahl bisher verbuchter Probes."""
        return self._probes

    def snapshot(self) -> CostSnapshot:
        """Aktueller Verbrauch als unveraenderliches Aggregat."""
        return CostSnapshot(
            probes=self._probes,
            total_tokens=self._tokens,
            total_usd=round(self._usd, 6),
            requests_by_provider=dict(self._requests),
        )
