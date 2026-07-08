"""Probing-Contracts: eine Engine-Abfrage und ihr normalisiertes Ergebnis.

Kern-Designentscheidung: ``Citation`` ist EIN Modell, auf das alle vier Engines
(Perplexity/Claude/ChatGPT/Gemini) ihr jeweils eigenes Rohformat abbilden. Der
``EnginePort`` garantiert dem Sampler dadurch ein einheitliches ``ProbeResult``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from geo_audit_loop.domain._base import FrozenModel


class EngineId(StrEnum):
    """Die vier in Sprint 1 beruecksichtigten Engines."""

    PERPLEXITY = "perplexity"
    CHATGPT = "chatgpt"
    CLAUDE = "claude"
    GEMINI = "gemini"


class SearchMode(StrEnum):
    """Perplexity-spezifischer Suchmodus (andere Engines ignorieren ihn)."""

    WEB = "web"
    ACADEMIC = "academic"
    SEC = "sec"


class ProbeStatus(StrEnum):
    """Ergebnisstatus einer einzelnen Probe."""

    OK = "ok"
    ERROR = "error"


class ProbePhase(StrEnum):
    """Phase einer Probe im geschlossenen Loop (Sprint 4).

    ``BASELINE`` ist die Erst-Messung; ``REPROBE`` misst denselben Matrix-Schnitt
    erneut NACH dem (Dry-Run-)Deploy, um den Effekt der Fixes zu erfassen. Die Phase
    ist Teil des Idempotenz-Schluessels, damit Baseline- und Re-Probe-Zellen unter
    derselben ``run_id`` kollisionsfrei koexistieren (Projektregeln §6).
    """

    BASELINE = "baseline"
    REPROBE = "reprobe"


class Citation(FrozenModel):
    """Eine normalisierte Quellenangabe, vereinheitlicht ueber alle Engines.

    Nur ``url`` ist Pflicht. ``published_date`` bleibt bewusst ein roher String
    (die Engines liefern unterschiedliche, teils unparsebare Formate). ``raw``
    haelt die verlustfreien Rohdaten der jeweiligen Engine.
    """

    url: str = Field(min_length=1)
    engine: EngineId
    title: str | None = None
    snippet: str | None = None
    published_date: str | None = None
    rank: int | None = Field(default=None, ge=1)  # 1-basierte Position in der Quellenliste
    raw: dict[str, Any] = Field(default_factory=dict)


class QueryIntent(StrEnum):
    """Fragetyp einer Nutzer-Query (Session 4, geschlossenes Vokabular).

    Hier (nicht in ``coverage``) definiert, weil ``ProbePrompt`` ihn traegt — ein
    separates Coverage-Modul als Heimat ergaebe einen Zirkular-Import.
    """

    INFORMATIONAL = "informational"  # "Was schreibt X vor / warum wichtig / Ueberblick"
    HOWTO = "howto"  # "Wie macht/baut/schuetzt man ..."
    COMPARISON = "comparison"  # "Welche/r ... ist empfehlenswert / Vergleich"
    DEFINITION = "definition"  # "Was ist X / wie funktioniert X"
    CHECKLIST = "checklist"  # "Welche Schritte / was gehoert in ..."
    TROUBLESHOOTING = "troubleshooting"  # "Woran erkennt man / bei einem Problem ..."


class ProbePrompt(FrozenModel):
    """Eine Zielfrage des versionierten Probe-Sets."""

    prompt_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    # Deterministischer Intent-Tag (Session 4). Optional (aeltere Probe-Sets ohne Tag laden weiter);
    # geht NICHT in ProbeRequest/ProbeResult ein -> Probe-Text/Checkpoint/Fingerprint unveraendert.
    intent: QueryIntent | None = None


class EngineProbeSpec(FrozenModel):
    """Pro-Engine-Parameter zum Bauen eines ProbeRequest (aus config abgeleitet).

    Haelt den Sampler config-frei: die Orchestrierung baut diese Spezifikation aus
    der Engine-Registry und reicht sie als reine Domaenendaten weiter.
    """

    engine_id: EngineId
    model: str = Field(min_length=1)
    max_tokens: int = Field(gt=0)
    temperature: float = Field(ge=0.0, le=2.0)
    search_mode: SearchMode | None = None


class ProbeRequest(FrozenModel):
    """Eine einzelne Engine-Abfrage (eine Zelle der 240er-Probe-Matrix)."""

    run_id: str = Field(min_length=1)
    engine_id: EngineId
    prompt_id: str = Field(min_length=1)
    prompt_text: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    model: str = Field(min_length=1)  # opaker Vendor-String aus config/

    target_domain: str = Field(min_length=1)
    proxy_label: str | None = None  # Label (KEIN Secret) der genutzten Proxy-IP
    proxy_index: int | None = Field(default=None, ge=0)  # Slot zur Proxy-Aufloesung im Adapter
    max_tokens: int = Field(gt=0)
    temperature: float = Field(ge=0.0, le=2.0)
    search_mode: SearchMode | None = None
    phase: ProbePhase = ProbePhase.BASELINE  # Baseline-Messung vs. Effekt-Re-Probe (Sprint 4)


class ProbeUsage(FrozenModel):
    """Token-/Request-Verbrauch einer Probe (speist den Budget-Cap, Projektregeln §6)."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    server_search_requests: int | None = None  # z.B. Anthropic usage.server_tool_use


class ProbeResult(FrozenModel):
    """Das normalisierte Ergebnis einer Probe (Rueckgabe des ``EnginePort``)."""

    run_id: str = Field(min_length=1)
    engine_id: EngineId
    model: str = Field(min_length=1)
    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    proxy_label: str | None = None
    answer_text: str = ""
    citations: tuple[Citation, ...] = ()
    target_cited: bool = False
    target_rank: int | None = None
    mentioned: bool = False  # Zieldomain/Marke im Antworttext erwaehnt (Mention-Rate)
    usage: ProbeUsage = Field(default_factory=ProbeUsage)
    status: ProbeStatus = ProbeStatus.OK
    error: str | None = None
    probed_at: datetime
    latency_ms: int = Field(default=0, ge=0)
    phase: ProbePhase = ProbePhase.BASELINE  # Baseline-Messung vs. Effekt-Re-Probe (Sprint 4)
