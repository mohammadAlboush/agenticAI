"""Template-Contracts: aus erfolgreich zitierten Inhalten geminte Best-Practice-Muster.

Ein ``Template`` ist konkret (prueft Merkmale), abstrahiert (gilt ueber eine Quelle
hinaus) und verankert (jedes Muster bindet an ``Lever`` + ``PyramidLevel``). Es ist
der Output des Pattern-Miners und der Massstab des GEO-Auditors.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.geo import Lever, PyramidLevel


class Template(FrozenModel):
    """Ein wiederverwendbares Muster erfolgreich zitierter Inhalte (Pattern-Miner)."""

    template_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    levers: tuple[Lever, ...] = Field(min_length=1)
    pyramid_level: PyramidLevel
    criteria: tuple[str, ...] = ()  # pruefbare Merkmale, nicht "schreib besser"
    evidence_urls: tuple[str, ...] = ()  # Top-Seiten, aus denen das Muster stammt
    confidence: float = Field(ge=0.0, le=1.0)


class PatternReport(FrozenModel):
    """Ergebnis des Pattern-Miners: die aus den Top-Seiten extrahierten Templates."""

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    generated_at: datetime
    source_urls: tuple[str, ...] = ()
    templates: tuple[Template, ...] = ()
