"""Engine-Preis-Tabelle fuer das Kosten-Tracking.

Approximative Preise (Stand 2026-06, aus dem Tech-Grounding). Plan-Risiko: vor einem
harten Live-Cap gegen die aktuelle Preisseite verifizieren. Unbekannte Modelle werden
mit ``DEFAULT_PRICE`` (0.0) bewertet und sollten geloggt werden.
"""

from __future__ import annotations

from geo_audit_loop.domain._base import FrozenModel


class Price(FrozenModel):
    """Preis je Modell in USD."""

    usd_per_1m_input: float = 0.0
    usd_per_1m_output: float = 0.0
    usd_per_search: float = 0.0


DEFAULT_PRICE: Price = Price()

PRICE_TABLE: dict[str, Price] = {
    # Perplexity Sonar (token-basiert; Citation-Tokens werden nicht berechnet)
    "sonar": Price(usd_per_1m_input=1.0, usd_per_1m_output=3.0),
    "sonar-pro": Price(usd_per_1m_input=3.0, usd_per_1m_output=15.0),
    # Claude (Web-Search-Tool ~ $10/1000 Suchen)
    "claude-sonnet-4-6": Price(usd_per_1m_input=3.0, usd_per_1m_output=15.0, usd_per_search=0.01),
    # ChatGPT / Gemini (Naeherung; in S1 ohnehin gemockt)
    "gpt-4o": Price(usd_per_1m_input=2.5, usd_per_1m_output=10.0),
    "gemini-2.0-flash": Price(usd_per_1m_input=0.1, usd_per_1m_output=0.4),
}
