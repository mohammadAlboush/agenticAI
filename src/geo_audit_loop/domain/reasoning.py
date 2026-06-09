"""Reasoning-Contracts: eine LLM-Reasoning-Anfrage und ihr normalisiertes Ergebnis.

Trennt das *inhaltliche Schliessen* (Claude) sauber vom SERP-artigen ``EnginePort``:
Pattern-Miner und GEO-Auditor haengen nur am ``ReasoningPort``, nie an einem SDK.
Der Vertrag ist modellunabhaengig (Text rein, Text + Usage raus).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from geo_audit_loop.domain._base import FrozenModel


class ReasoningStatus(StrEnum):
    """Ergebnisstatus eines Reasoning-Aufrufs."""

    OK = "ok"
    ERROR = "error"


class ReasoningUsage(FrozenModel):
    """Token-Verbrauch eines Reasoning-Aufrufs (speist den Budget-Cap, Projektregeln §6)."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ReasoningRequest(FrozenModel):
    """Eine einzelne LLM-Reasoning-Anfrage (System + Prompt, modellunabhaengig)."""

    run_id: str = Field(min_length=1)
    task: str = Field(min_length=1)  # Label des Agentenschritts, z.B. "pattern_miner"
    system: str = ""
    prompt_text: str = Field(min_length=1)
    model: str = Field(min_length=1)  # opaker Vendor-String aus config/
    max_tokens: int = Field(gt=0)
    temperature: float = Field(ge=0.0, le=2.0)
    seed: int | None = None  # Determinismus-Anker fuer den Mock-Adapter


class ReasoningResult(FrozenModel):
    """Das normalisierte Ergebnis eines Reasoning-Aufrufs (Rueckgabe des ``ReasoningPort``)."""

    run_id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    model: str = Field(min_length=1)
    text: str = ""
    usage: ReasoningUsage = Field(default_factory=ReasoningUsage)
    status: ReasoningStatus = ReasoningStatus.OK
    error: str | None = None
    generated_at: datetime
    latency_ms: int = Field(default=0, ge=0)
