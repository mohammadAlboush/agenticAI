"""Run-Identitaet und -Status (Reproduzierbarkeits-Anker, Projektregeln §7)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from geo_audit_loop.domain._base import FrozenModel


class RunStatus(StrEnum):
    """Lebenszyklus eines Runs."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class RunContext(FrozenModel):
    """Unveraenderlicher Kontext, der durch alle Agentenschritte propagiert wird.

    Buendelt alles, was einen Lauf reproduzierbar macht: ``run_id`` (in allen
    Logs/DB-Zeilen), ``seed`` (deterministische Proxy-Rotation/Mock), die
    genutzte ``prompt_set_version`` und ein ``config_hash`` der Run-Konfiguration.
    """

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    started_at: datetime
    seed: int
    prompt_set_version: str = Field(min_length=1)
    config_hash: str = Field(min_length=1)


class RunRecord(FrozenModel):
    """Persistierter Run-Zustand inklusive aggregierter Kennzahlen.

    Aktualisierungen erfolgen funktional via ``model_copy(update=...)`` statt
    Mutation (das Modell ist ``frozen``).
    """

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    seed: int
    prompt_set_version: str
    config_hash: str
    total_probes: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    error: str | None = None
