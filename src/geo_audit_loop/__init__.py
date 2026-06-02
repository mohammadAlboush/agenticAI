"""geo-audit-loop: selbstlernendes agentisches GEO/SEO-Audit-System.

Hexagonale Architektur (Ports & Adapters). Der Kern (``domain`` + ``ports``)
kennt keine konkrete Aussenwelt; Adapter implementieren die Ports, Agenten und
Orchestrierung haengen ausschliesslich an ``domain`` und ``ports``.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
