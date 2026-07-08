"""Effekt-Analyst (Sprint 4): misst den Fix-Effekt und schreibt ihn ins Gedaechtnis.

Ein **deterministischer** Agent (wie Sampler/Crawler — kein LLM, kein RNG): er liest die
Baseline- und Re-Probe-Ergebnisse eines Runs aus der Persistenz, bildet ueber die reine
Domaenenfunktion ``form_effect_report`` je angewandtem Patch eine ``EffectHypothesis``,
persistiert den ``EffectReport`` (``StoragePort``) und legt jede Hypothese ins Gedaechtnis
(``MemoryPort.store``) — die Grundlage, aus der der naechste Fix-Run lernt (Projektregeln §8).
Haengt nur an ``domain`` + ``ports`` (Projektregeln §3.1).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from collections.abc import Sequence as Seq
from datetime import UTC, datetime

from geo_audit_loop.domain.effect import EffectReport, form_effect_report
from geo_audit_loop.domain.fix import FixProposal
from geo_audit_loop.domain.probe import ProbePhase
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.ports.memory import MemoryPort
from geo_audit_loop.ports.storage import StoragePort

_AGENT = "effect_analyst"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EffectAnalystService:
    """Bildet aus Baseline vs. Re-Probe die Effekt-Hypothesen und speichert sie (MemoryPort)."""

    def __init__(
        self,
        *,
        memory: MemoryPort,
        storage: StoragePort,
        logger: logging.Logger | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._memory = memory
        self._storage = storage
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._clock = clock if clock is not None else _utc_now

    def run(
        self,
        run_context: RunContext,
        applied: Seq[FixProposal],
        prompt_version: str,
    ) -> EffectReport:
        """Misst den Effekt der angewandten Patches und schreibt die Hypothesen ins Gedaechtnis.

        Args:
            run_context: Der laufende Kontext (run_id/Domain/Seed).
            applied: Die tatsaechlich (freigegeben) angewandten Patches.
            prompt_version: Version des Fix-Prompts, der den getesteten Plan erzeugte.

        Returns:
            Der persistierte ``EffectReport`` (eine Hypothese je angewandtem Patch).
        """
        before = self._storage.load_probes(run_context.run_id, ProbePhase.BASELINE)
        after = self._storage.load_probes(run_context.run_id, ProbePhase.REPROBE)
        report = form_effect_report(
            run_id=run_context.run_id,
            target_domain=run_context.target_domain,
            before_probes=before,
            after_probes=after,
            applied=applied,
            prompt_version=prompt_version,
            generated_at=self._clock(),
        )
        self._storage.save_effect_report(report)
        for hypothesis in report.hypotheses:
            self._memory.store(hypothesis)
        log_event(
            self._log,
            "effect.done",
            run_id=run_context.run_id,
            agent=_AGENT,
            n_hypotheses=len(report.hypotheses),
            n_improved=report.n_improved,
            mean_delta=report.mean_delta,
        )
        return report
