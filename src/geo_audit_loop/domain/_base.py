"""Gemeinsame Pydantic-Basis fuer alle Domaenen-Contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Unveraenderlicher, strikt validierter Datenvertrag.

    ``frozen=True`` macht Instanzen unveraenderlich (Contracts werden einmal
    erzeugt und danach nur kopiert), ``extra='forbid'`` verhindert das stille
    Durchreichen unbekannter Felder zwischen Agenten (Projektregeln §3.2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
