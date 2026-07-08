"""Findings-Contracts: Seiten-Score und Top/Flop-Report (Sprint-1-Demo-Ausgabe).

Sprint 6: jede Seite traegt ein **Wilson-Konfidenzintervall** ihrer Zitationsrate und ein
**Sichtbarkeits-Band** relativ zum Domain-Durchschnitt. So ruht die gesamte nachgelagerte
Pipeline (Pattern-Miner, GEO-Auditor) nicht mehr auf rohen Zaehlungen: eine Seite gilt nur
dann als belastbar ueber-/unterdurchschnittlich, wenn ihr KI den Domain-Schnitt ausschliesst —
zwei Seiten, die sich nur um wenige Zitate von 240 unterscheiden, sind statistisch gleich
(Projektregeln §1: wissenschaftliche Aussagekraft).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from geo_audit_loop.domain._base import FrozenModel
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.metrics import ProbeAggregate


class VisibilityBand(StrEnum):
    """Statistische Einordnung einer Seite relativ zum Domain-Schnitt (geschlossenes Vokabular)."""

    ABOVE_FIELD = "above_field"  # KI der Rate komplett ueber dem Domain-Schnitt (belastbar top)
    TYPICAL = "typical"  # KI umschliesst den Domain-Schnitt -> nicht unterscheidbar (Rauschen)
    BELOW_FIELD = "below_field"  # KI komplett unter dem Domain-Schnitt (belastbar flop)


def classify_band(rate_ci_low: float, rate_ci_high: float, field_rate: float) -> VisibilityBand:
    """Ordnet eine Seite anhand ihres Raten-KI relativ zum Domain-Durchschnitt ein.

    ``field_rate`` ist die mittlere Zitationsrate ueber alle Seiten der Domain (Referenzniveau).
    Schliesst das KI diese Referenz aus, ist die Seite belastbar ueber-/unterdurchschnittlich;
    sonst ist der Unterschied statistisch nicht belastbar -> ``TYPICAL``. Die Referenz schliesst
    die Seite selbst bewusst mit ein ("ueber dem Domain-Schnitt", nicht "ueber den uebrigen
    Seiten") — eine leichte, konservative Verzerrung Richtung ``TYPICAL``, die die natuerliche
    Frage "welche Seiten uebertreffen den Domain-Durchschnitt?" korrekt abbildet.
    """
    if rate_ci_low > field_rate:
        return VisibilityBand.ABOVE_FIELD
    if rate_ci_high < field_rate:
        return VisibilityBand.BELOW_FIELD
    return VisibilityBand.TYPICAL


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
    """Eine Zeile in der Top- oder Flop-Liste (mit statistischer Unsicherheit, Sprint 6)."""

    position: int = Field(ge=1)
    url: str = Field(min_length=1)
    citation_count: int = Field(ge=0)
    citation_rate: float = Field(ge=0.0, le=1.0)
    # 95%-Wilson-KI der Zitationsrate. Defaults = maximale Unsicherheit fuer hand-konstruierte
    # Zeilen ohne Messung; der Builder setzt sie stets aus (citation_count, n_probes).
    rate_ci_low: float = Field(default=0.0, ge=0.0, le=1.0)
    rate_ci_high: float = Field(default=1.0, ge=0.0, le=1.0)
    band: VisibilityBand = VisibilityBand.TYPICAL  # Einordnung relativ zum Domain-Schnitt
    best_rank: int | None = None


class TopFlopReport(FrozenModel):
    """Die Sprint-1-Demo-Ausgabe: neutrale Top/Flop-Sichtbarkeit fuer eine Domain."""

    run_id: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    generated_at: datetime
    n_probes: int = Field(ge=0)
    n_pages: int = Field(ge=0)
    field_citation_rate: float = Field(default=0.0, ge=0.0, le=1.0)  # Domain-Schnitt (Referenz)
    top: tuple[TopFlopEntry, ...] = ()
    flop: tuple[TopFlopEntry, ...] = ()
    engine_aggregates: tuple[ProbeAggregate, ...] = ()
