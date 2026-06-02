"""Kosten-Tracking und harter Budget-Cap pro Run (Projektregeln §6).

Trennung: die Engine-Adapter kennen kein Budget; der Sampler ruft vor jeder Probe
``ensure_can_probe()`` und nach jeder Probe ``record()``. Wird ein Limit erreicht,
bricht der naechste ``ensure_can_probe()`` mit ``BudgetExceeded`` sauber ab.
"""

from __future__ import annotations

from geo_audit_loop.config.pricing import DEFAULT_PRICE, Price
from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.errors import BudgetExceeded
from geo_audit_loop.domain.probe import ProbeUsage


class CostSnapshot(FrozenModel):
    """Aggregierter Verbrauch eines Runs."""

    probes: int
    total_tokens: int
    total_usd: float


class CostTracker:
    """Zaehlt Probes, Tokens und USD-Kosten und erzwingt die harten Limits."""

    def __init__(
        self,
        *,
        max_probes: int,
        max_usd: float,
        max_tokens: int,
        price_table: dict[str, Price] | None = None,
    ) -> None:
        self._max_probes = max_probes
        self._max_usd = max_usd
        self._max_tokens = max_tokens
        self._prices = price_table if price_table is not None else {}
        self._probes = 0
        self._tokens = 0
        self._usd = 0.0

    def ensure_can_probe(self) -> None:
        """Wirft ``BudgetExceeded``, falls ein Limit erreicht ist (harter Cap, einheitlich ``>=``).

        Alle drei Limits werden konsistent als "weitermachen nur, solange strikt unter dem
        Cap" geprueft: ein Lauf startet keine Probe, sobald Probes, Tokens oder USD das
        jeweilige Limit erreichen (Projektregeln §6).
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
        )
