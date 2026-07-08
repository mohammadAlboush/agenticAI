"""Engine-Adapter: deterministischer Mock (kein Netz) fuer Offline-Pipeline und Tests.

Die Zitate sind reproduzierbar aus ``(seed, engine, prompt_id, proxy_label)`` abgeleitet.
Ziel-URLs mit niedrigem Index werden haeufiger zitiert (absteigende Gewichte) -> es
entsteht eine plausible Top/Flop-Verteilung, ohne echte Engine-Calls.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from geo_audit_loop.domain.metrics import evaluate_target
from geo_audit_loop.domain.probe import (
    Citation,
    EngineId,
    ProbeRequest,
    ProbeResult,
    ProbeStatus,
    ProbeUsage,
)

_EXTERNAL_URLS: tuple[str, ...] = (
    "https://www.bsi.bund.de/grundschutz",
    "https://de.wikipedia.org/wiki/IT-Sicherheit",
    "https://www.heise.de/security",
)
_CITATION_COUNT_WEIGHTS = (2, 5, 3)  # P(0), P(1), P(2) Ziel-Zitate


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MockEngineAdapter:
    """Liefert deterministische ``ProbeResult``s (erfuellt ``EnginePort``)."""

    def __init__(
        self,
        engine_id: EngineId,
        *,
        target_urls: Sequence[str] = (),
        seed: int = 0,
        boosted_urls: Sequence[str] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine_id = engine_id
        self._target_urls = tuple(target_urls)
        self._seed = seed
        # Sprint-4-Effekt-Simulation: URLs mit angewandtem Patch werden in der Re-Probe
        # GARANTIERT zitiert (deterministischer Vorher/Nachher-Lift). Leer => Baseline-Verhalten.
        self._boosted = tuple(dict.fromkeys(boosted_urls))
        self._clock = clock if clock is not None else _utc_now

    @property
    def engine_id(self) -> EngineId:
        """Identitaet der gemockten Engine."""
        return self._engine_id

    def _rng(self, request: ProbeRequest) -> random.Random:
        key = f"{self._seed}|{request.engine_id.value}|{request.prompt_id}|{request.proxy_label}"
        seed_int = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
        return random.Random(seed_int)

    def _pick_target_urls(self, rng: random.Random) -> list[str]:
        if not self._target_urls:
            return []
        count = rng.choices((0, 1, 2), weights=_CITATION_COUNT_WEIGHTS, k=1)[0]
        if count == 0:
            return []
        weights = [len(self._target_urls) - i for i in range(len(self._target_urls))]
        picked = rng.choices(self._target_urls, weights=weights, k=count)
        return list(dict.fromkeys(picked))  # De-Dup, Reihenfolge stabil

    def probe(self, request: ProbeRequest) -> ProbeResult:
        """Erzeugt ein deterministisches, plausibles ``ProbeResult`` (kein Netz)."""
        rng = self._rng(request)
        target_hits = self._pick_target_urls(rng)
        # Boost NACH dem RNG-Zug: kein zusaetzlicher Zufallsschritt -> die Baseline-Ziehung
        # bleibt bit-identisch (leerer Boost == unveraendertes Verhalten). Angewandte Patch-URLs
        # werden garantiert ergaenzt -> Re-Probe misst einen deterministischen positiven Effekt.
        for url in self._boosted:
            if url not in target_hits:
                target_hits.append(url)
        external = rng.sample(_EXTERNAL_URLS, k=rng.randint(1, len(_EXTERNAL_URLS)))

        urls = target_hits + external
        rng.shuffle(urls)
        citations = tuple(
            Citation(url=url, engine=self._engine_id, rank=rank, title=f"Quelle {rank}")
            for rank, url in enumerate(urls, start=1)
        )

        cited, rank = evaluate_target(citations, request.target_domain)
        mentioned = cited or rng.random() < 0.3
        usage = ProbeUsage(prompt_tokens=40, completion_tokens=120, total_tokens=160)
        return ProbeResult(
            run_id=request.run_id,
            engine_id=self._engine_id,
            model=request.model,
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            proxy_label=request.proxy_label,
            answer_text=f"[mock:{self._engine_id.value}] Antwort auf {request.prompt_id}.",
            citations=citations,
            target_cited=cited,
            target_rank=rank,
            mentioned=mentioned,
            usage=usage,
            status=ProbeStatus.OK,
            probed_at=self._clock(),
        )
