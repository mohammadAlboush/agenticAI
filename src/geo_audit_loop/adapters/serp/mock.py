"""SERP-Adapter: deterministischer Mock (kein Netz) fuer Offline-Pipeline und Tests.

Die Trefferliste ist reproduzierbar aus ``(seed, query_id)`` abgeleitet (Muster
``MockEngineAdapter._rng``). Der Pool mischt Ziel-URLs (``sample_target_urls``) mit
festen Fremd-Domains; ein Teil der Fremdtreffer entspricht ABSICHTLICH den Zitaten
des Engine-Mocks (BSI/Wikipedia/Heise) — so entsteht eine partielle, stabile
Ueberschneidung zwischen Google-Top-K und AI-Zitaten (interessante Golden-Werte
statt Jaccard 0 oder 1). Ziel-URLs landen mal in den Top-K, mal nicht ->
``target_serp_rank`` variiert deterministisch je Query.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable
from datetime import UTC, datetime

from geo_audit_loop.adapters.sample_data import SAMPLE_DOMAIN, sample_target_urls
from geo_audit_loop.domain.probe import ProbeStatus
from geo_audit_loop.domain.serp import RankEntry, SerpProvider, SerpRequest, SerpResult

# Fremdtreffer, die der Engine-Mock EBENFALLS zitiert (partielle Ueberschneidung).
_OVERLAP_URLS: tuple[str, ...] = (
    "https://www.bsi.bund.de/grundschutz",
    "https://de.wikipedia.org/wiki/IT-Sicherheit",
    "https://www.heise.de/security",
)
# Fremdtreffer, die NUR in der SERP auftauchen (nie in den Engine-Zitaten).
_FOREIGN_URLS: tuple[str, ...] = (
    "https://www.golem.de/security",
    "https://www.security-insider.de/grundlagen",
    "https://www.computerwoche.de/it-sicherheit",
    "https://www.bitkom.org/cybersicherheit",
    "https://www.allianz-fuer-cybersicherheit.de/empfehlungen",
    "https://www.zdnet.de/it-security",
    "https://www.datenschutz.org/ratgeber",
)
_TARGET_COUNT_WEIGHTS = (2, 5, 3)  # P(0), P(1), P(2) Ziel-Treffer in den Top-K


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MockSerpAdapter:
    """Liefert deterministische ``SerpResult``s (erfuellt ``SerpPort``)."""

    def __init__(
        self,
        *,
        domain: str = SAMPLE_DOMAIN,
        seed: int = 0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._target_urls = tuple(sample_target_urls(domain))
        self._seed = seed
        self._clock = clock if clock is not None else _utc_now

    @property
    def provider(self) -> SerpProvider:
        """Identitaet der gemockten SERP-Quelle."""
        return SerpProvider.MOCK

    def _rng(self, query_id: str) -> random.Random:
        key = f"{self._seed}|serp|{query_id}"
        seed_int = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
        return random.Random(seed_int)

    def _pick_target_urls(self, rng: random.Random) -> list[str]:
        count = rng.choices((0, 1, 2), weights=_TARGET_COUNT_WEIGHTS, k=1)[0]
        if count == 0:
            return []
        # Absteigende Gewichte: fruehe Ziel-URLs ranken haeufiger (plausible Verteilung).
        weights = [len(self._target_urls) - i for i in range(len(self._target_urls))]
        picked = rng.choices(self._target_urls, weights=weights, k=count)
        return list(dict.fromkeys(picked))  # De-Dup, Reihenfolge stabil

    def search(self, request: SerpRequest) -> SerpResult:
        """Erzeugt ein deterministisches, plausibles ``SerpResult`` (kein Netz)."""
        rng = self._rng(request.query.query_id)
        target_hits = self._pick_target_urls(rng)
        overlap = rng.sample(_OVERLAP_URLS, k=rng.randint(1, len(_OVERLAP_URLS)))
        picked = target_hits + overlap
        remaining = max(0, request.top_k - len(picked))
        picked += rng.sample(_FOREIGN_URLS, k=min(remaining, len(_FOREIGN_URLS)))
        urls = picked[: request.top_k]
        rng.shuffle(urls)
        entries = tuple(
            RankEntry(
                url=url,
                position=position,
                title=f"Treffer {position}",
                snippet=f"Snippet zu '{request.query.text}'",
            )
            for position, url in enumerate(urls, start=1)
        )
        return SerpResult(
            run_id=request.run_id,
            provider=SerpProvider.MOCK,
            query_id=request.query.query_id,
            prompt_id=request.query.prompt_id,
            query_text=request.query.text,
            entries=entries,
            status=ProbeStatus.OK,
            fetched_at=self._clock(),
            # Konstant 0: der Offline-Pfad muss bit-reproduzierbar sein (kein Timing-Rauschen).
            latency_ms=0,
        )
