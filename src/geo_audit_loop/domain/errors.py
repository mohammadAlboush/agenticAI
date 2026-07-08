"""Domaenenspezifische Fehlertypen (Projektregeln §4: keine nackten Exceptions)."""

from __future__ import annotations


class GeoAuditError(Exception):
    """Basisklasse aller geo-audit-loop-Fehler."""


class ConfigError(GeoAuditError):
    """Fehlerhafte oder fehlende Konfiguration."""


class EngineError(GeoAuditError):
    """Fehler bei der Abfrage einer Such-/AI-Engine."""


class ReasoningError(GeoAuditError):
    """Nicht behebbarer Fehler eines LLM-Reasoning-Adapters (z.B. fehlender API-Key)."""


class ProxyError(GeoAuditError):
    """Fehler bei Beschaffung oder Nutzung eines Proxys."""


class CrawlError(GeoAuditError):
    """Fehler beim Crawlen der Zielseite."""


class StorageError(GeoAuditError):
    """Fehler bei der Persistenz (SQLite)."""


class DeployBlocked(GeoAuditError):
    """Deploy ohne Human-in-the-Loop-Freigabe versucht (Projektregeln §6: HITL-Gate hart)."""


class BudgetExceeded(GeoAuditError):
    """Hartes Run-Limit ueberschritten (Projektregeln §6: sauber abbrechen, nicht weiterlaufen)."""

    def __init__(self, message: str, *, limit_name: str, limit: float, used: float) -> None:
        super().__init__(message)
        self.limit_name = limit_name
        self.limit = limit
        self.used = used
