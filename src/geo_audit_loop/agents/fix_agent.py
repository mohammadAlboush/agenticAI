"""Fix-Agent: aus priorisierten ``AuditFinding``s konkrete ``FixProposal``s (LLM-getrieben).

Nimmt den ``AuditReport``, die orientierenden Templates und das Flop-Seiten-Inventar, baut daraus
einen Prompt, ruft den ``ReasoningPort`` und parst die Antwort in ``FixProposal``s. Die Patches
werden nach der Citation-Pyramide priorisiert (untere Ebene zuerst). Der Agent formuliert nur
Aenderungen — die Freigabe (HITL) und der Deploy passieren danach in der Orchestrierung.
Haengt nur an domain, ports, prompts-Text und observability (Projektregeln §3.1).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from collections.abc import Sequence as Seq
from datetime import UTC, datetime
from typing import Any, Final

from pydantic import ValidationError

from geo_audit_loop.agents._parsing import extract_json_object, page_features
from geo_audit_loop.config import constants as c
from geo_audit_loop.domain.audit import AuditReport
from geo_audit_loop.domain.effect import EffectHypothesis
from geo_audit_loop.domain.errors import ReasoningError
from geo_audit_loop.domain.fix import FixPlan, FixProposal, prioritize_proposals
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.memory import apply_memory_prior
from geo_audit_loop.domain.probe import ProbeUsage
from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningResult, ReasoningStatus
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.domain.templates import PatternReport
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.ports.reasoning import ReasoningPort
from geo_audit_loop.ports.storage import StoragePort

_AGENT: Final = "fix_agent"
_TASK: Final = c.FIX_AGENT_TASK
_MAX_ATTEMPTS: Final = 2  # ein Reasoning-Aufruf + ein Retry bei Schema-/Parse-Fehler

# JSON-Schema fuer Tool-Use (Live-LLM erzwingt damit valide Ausgabe; Mock ignoriert es).
_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "patch_id": {"type": "string"},
                    "finding_id": {"type": "string"},
                    "target_url": {"type": "string"},
                    "lever": {"type": "string"},
                    "pyramid_level": {"type": "string"},
                    "change_type": {"type": "string"},
                    "current_excerpt": {"type": "string"},
                    "proposed_content": {"type": "string"},
                    "unified_diff": {"type": "string"},
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number"},
                    "template_id": {"type": ["string", "null"]},
                },
                "required": [
                    "patch_id",
                    "finding_id",
                    "target_url",
                    "lever",
                    "pyramid_level",
                    "change_type",
                    "proposed_content",
                    "rationale",
                    "confidence",
                ],
            },
        }
    },
    "required": ["proposals"],
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FixAgentService:
    """Leitet aus den Findings konkrete, priorisierte ``FixProposal``s ab."""

    def __init__(
        self,
        *,
        reasoning: ReasoningPort,
        system_prompt: str,
        prompt_version: str,
        cost_tracker: CostTracker,
        max_tokens: int = c.DEFAULT_MAX_TOKENS,
        temperature: float = c.REASONING_TEMPERATURE,
        storage: StoragePort | None = None,
        logger: logging.Logger | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._reasoning = reasoning
        self._system = system_prompt
        self._prompt_version = prompt_version
        self._cost = cost_tracker
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._storage = storage
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._clock = clock if clock is not None else _utc_now

    def run(
        self,
        run_context: RunContext,
        audit: AuditReport,
        patterns: PatternReport,
        pages: Seq[PageInventory],
        memory_hypotheses: Seq[EffectHypothesis] = (),
    ) -> FixPlan:
        """Baut aus Findings + Templates + Inventar den priorisierten Fix-Plan.

        ``memory_hypotheses`` (Sprint 4) sind aus dem Gedaechtnis abgerufene, erwiesene
        Effekte: sie fliessen EXPLIZIT in den Prompt (Live-LLM) UND deterministisch ueber
        ``apply_memory_prior`` in die Confidence/Priorisierung (offline nachweisbar, §8).
        Leer => bit-genau das Sprint-3-Verhalten.
        """
        by_url = {inv.page.url: inv for inv in pages}
        prompt = self._build_prompt(audit, patterns, by_url, memory_hypotheses)
        proposals = self._propose(run_context, prompt)
        learned = apply_memory_prior(proposals, memory_hypotheses)
        log_event(
            self._log,
            "fix.done",
            run_id=run_context.run_id,
            agent=_AGENT,
            prompt_version=self._prompt_version,
            n_proposals=len(learned),
            n_memory=len(memory_hypotheses),
        )
        return FixPlan(
            run_id=run_context.run_id,
            target_domain=run_context.target_domain,
            generated_at=self._clock(),
            prompt_version=self._prompt_version,
            proposals=prioritize_proposals(learned),
        )

    def _build_prompt(
        self,
        audit: AuditReport,
        patterns: PatternReport,
        pages_by_url: dict[str, PageInventory],
        memory_hypotheses: Seq[EffectHypothesis] = (),
    ) -> str:
        findings_brief = [f.model_dump(mode="json") for f in audit.findings]
        templates_brief = [
            {
                "template_id": t.template_id,
                "title": t.title,
                "summary": t.summary,
                "criteria": list(t.criteria),
            }
            for t in patterns.templates
        ]
        cited_urls = {f.target_url for f in audit.findings}
        page_brief = [page_features(pages_by_url[u]) for u in cited_urls if u in pages_by_url]
        memory_block = self._render_memory(memory_hypotheses)
        return (
            "Priorisierte Findings des GEO-Auditors:\n"
            f"{json.dumps(findings_brief, ensure_ascii=False, indent=2)}\n\n"
            "Orientierende Best-Practice-Templates:\n"
            f"{json.dumps(templates_brief, ensure_ascii=False, indent=2)}\n\n"
            "On-Page-Inventar der betroffenen Flop-Seiten:\n"
            f"{json.dumps(page_brief, ensure_ascii=False, indent=2)}\n\n"
            f"{memory_block}"
            "Mache aus jedem Finding genau einen konkreten Patch. Gib NUR das JSON-Objekt zurueck."
        )

    @staticmethod
    def _render_memory(memory_hypotheses: Seq[EffectHypothesis]) -> str:
        """Rendert erwiesene Effekt-Hypothesen als expliziten Prompt-Block (§8; leer => "").

        Jede Hypothese traegt ihr 95%-Konfidenzintervall und das ``significant``-Flag: nur
        signifikante Effekte (KI schliesst die Null aus) sind belastbar — genau die, die auch
        der deterministische ``apply_memory_prior`` gewichtet. Prompt- und Code-Pfad wirken so
        in dieselbe Richtung (Sprint 5).
        """
        if not memory_hypotheses:
            return ""
        learned = [
            {
                "lever": h.lever.value,
                "change_type": h.change_type.value,
                "delta_citation_rate": h.delta,
                "ci_95": [h.ci_low, h.ci_high],
                "significant": h.significant,
                "confidence": h.confidence,
                "direction": h.direction.value,
            }
            for h in memory_hypotheses
        ]
        return (
            "Fruehere Effekt-Hypothesen aus dem Gedaechtnis (Vorher/Nachher gemessen, mit 95%-KI). "
            "Bevorzuge Hebel/Aenderungsarten mit erwiesen positivem delta_citation_rate UND "
            "significant=true; ignoriere nicht-signifikante Effekte als Rauschen:\n"
            f"{json.dumps(learned, ensure_ascii=False, indent=2)}\n\n"
        )

    def _propose(self, run_context: RunContext, prompt: str) -> tuple[FixProposal, ...]:
        last_error = "kein Versuch ausgefuehrt"
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            self._cost.ensure_within_budget()
            result = self._reasoning.reason(self._request(run_context, prompt))
            self._record(result)
            if self._storage is not None:
                self._storage.append_reasoning_log(
                    run_context.run_id, _TASK, result.model, self._prompt_version, result.text
                )
            if result.status is ReasoningStatus.ERROR:
                last_error = result.error or "Reasoning-Fehler"
            else:
                try:
                    return self._parse(result.text, run_context.run_id)
                except (ReasoningError, ValidationError) as exc:
                    last_error = str(exc)
            log_event(
                self._log,
                "fix.retry",
                run_id=run_context.run_id,
                agent=_AGENT,
                attempt=attempt,
                error=last_error,
                level=logging.WARNING,
            )
        raise ReasoningError(
            f"Fix-Agent fehlgeschlagen nach {_MAX_ATTEMPTS} Versuchen: {last_error}"
        )

    def _request(self, run_context: RunContext, prompt: str) -> ReasoningRequest:
        return ReasoningRequest(
            run_id=run_context.run_id,
            task=_TASK,
            system=self._system,
            prompt_text=prompt,
            model=self._reasoning.model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            seed=run_context.seed,
            response_schema=_RESPONSE_SCHEMA,
        )

    def _record(self, result: ReasoningResult) -> None:
        self._cost.record_reasoning(
            result.model,
            ProbeUsage(
                prompt_tokens=result.usage.input_tokens,
                completion_tokens=result.usage.output_tokens,
                total_tokens=result.usage.total_tokens,
            ),
        )

    def _parse(self, text: str, run_id: str) -> tuple[FixProposal, ...]:
        data = extract_json_object(text)
        raw = data.get("proposals")
        if not isinstance(raw, list):
            raise ReasoningError("Reasoning-JSON enthaelt kein 'proposals'-Array")
        proposals: list[FixProposal] = []
        for item in raw:  # pro Item validieren: gueltige behalten, ungueltige loggen
            try:
                proposals.append(FixProposal.model_validate(item))
            except ValidationError as exc:
                log_event(
                    self._log,
                    "fix.item_dropped",
                    run_id=run_id,
                    agent=_AGENT,
                    error=str(exc),
                    level=logging.WARNING,
                )
        if not proposals:
            raise ReasoningError("keine gueltigen Proposals extrahiert")
        return tuple(proposals)
