"""Findings-Contracts: Seiten-Score und Top/Flop-Report (Sprint-1-Demo-Ausgabe)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.metrics import ProbeAggregate


class PageScore(FrozenModel):
    """Sichtbarkeits-Score einer einzelnen Seite der Zieldomain.

    ``citation_rate = citation_count / n_probes`` ist die neutrale, ueber alle
    Engines/Prompts/Proxy-IPs gemittelte Sichtbarkeit dieser konkreten URL.
    """

    url: str = Field(min_length=1)
    citation_count: int = Field(ge=0)
    n_probes: int = Field(ge=0)
    citation_rate: float = Field(ge=0.0, le=1.0)
    best_rank: int | None = None
    inventory: PageInventory | None = None


class TopFlopEntry(FrozenModel):
    """Eine Zeile in der Top- oder Flop-Liste."""

    position: int = Field(ge=1)
    url: str = Field(min_length=1)
    citation_count: int = Field(ge=0)
    citation_rate: float = Field(ge=0.0, le=1.0)
    best_rank: int | None = None


class TopFlopReport(FrozenModel):
    """Die Sprint-1-Demo-Ausgabe: neutrale Top/Flop-Sichtbarkeit fuer eine Domain."""

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    generated_at: datetime
    n_probes: int = Field(ge=0)
    n_pages: int = Field(ge=0)
    top: tuple[TopFlopEntry, ...] = ()
    flop: tuple[TopFlopEntry, ...] = ()
    engine_aggregates: tuple[ProbeAggregate, ...] = ()
