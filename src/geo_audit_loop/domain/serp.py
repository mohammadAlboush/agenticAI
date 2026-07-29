"""SERP-Contracts (Live-Loop): klassische Google-Top-Treffer als Vergleichsmenge.

Die Kernthese des Projekts („Die Ueberlappung zwischen Google-Top-Treffern und
AI-zitierten Quellen ist gesunken") braucht eine zweite Messgroesse neben den
Engine-Probes: die organischen Google-Treffer je Keyword-Query. ``RankEntry`` ist
bewusst NICHT ``Citation`` — ein SERP-Treffer ist ein Ranking-Ergebnis, kein
AI-Beleg (andere Semantik, andere Pflichtfelder). Der Topic-Join zur Probe-Matrix
laeuft ueber ``SerpQuery.prompt_id``: jede Keyword-Query gehoert zu genau einem
Probe-Prompt desselben Themas.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.probe import ProbeStatus


class SerpProvider(StrEnum):
    """Quelle der SERP-Daten (geschlossenes Vokabular)."""

    MOCK = "mock"  # seed-deterministisch, offline
    SERPER = "serper"  # google.serper.dev (Live)


class SerpQuery(FrozenModel):
    """Eine Keyword-Query des versionierten SERP-Query-Sets.

    ``prompt_id`` ist der Topic-Join: die Query misst dasselbe Thema wie der
    gleichnamige Probe-Prompt (Grundlage des Overlap-Vergleichs).
    """

    query_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    prompt_id: str = Field(min_length=1)


class SerpRequest(FrozenModel):
    """Eine einzelne SERP-Abfrage (Eingabe des ``SerpPort``)."""

    run_id: str = Field(min_length=1)
    query: SerpQuery
    top_k: int = Field(default=c.SERP_TOP_K, ge=1)
    gl: str = Field(default=c.SERP_GL, min_length=2)  # Land (Geolokation)
    hl: str = Field(default=c.SERP_HL, min_length=2)  # Interface-Sprache


class RankEntry(FrozenModel):
    """Ein organischer SERP-Treffer (bewusst KEINE ``Citation`` — andere Semantik)."""

    url: str = Field(min_length=1)
    position: int = Field(ge=1)  # 1-basierte organische Position
    title: str | None = None
    snippet: str | None = None


class SerpResult(FrozenModel):
    """Das normalisierte Ergebnis einer SERP-Abfrage (Rueckgabe des ``SerpPort``).

    ``status`` verwendet das bestehende ``ProbeStatus``-Vokabular: transiente
    Fehler werden als ``ERROR``-Ergebnis abgebildet, nie als Exception (Muster
    ``EnginePort``). ``(run_id, provider, query_id)`` ist der Checkpoint-Schluessel
    der Persistenz (Idempotenz, Projektregeln §6).
    """

    run_id: str = Field(min_length=1)
    provider: SerpProvider
    query_id: str = Field(min_length=1)
    prompt_id: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    entries: tuple[RankEntry, ...] = ()
    status: ProbeStatus = ProbeStatus.OK
    error: str | None = None
    fetched_at: datetime
    latency_ms: int = Field(default=0, ge=0)
