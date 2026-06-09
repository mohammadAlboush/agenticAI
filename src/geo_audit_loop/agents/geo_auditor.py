"""GEO-Auditor-Agent: prueft die Flop-Seiten gegen die geminten Templates (LLM-getrieben).

Nimmt den Top/Flop-Report, das Seiten-Inventar und den ``PatternReport``, baut aus den
Flop-Seiten + Templates einen Prompt, ruft den ``ReasoningPort`` und parst die Antwort in
``AuditFinding``s. Die Findings werden nach der Citation-Pyramide priorisiert (untere Ebene
zuerst). Haengt nur an domain, ports, prompts-Text und observability.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from collections.abc import Sequence as Seq
from datetime import UTC, datetime
from typing import Final

from pydantic import ValidationError

from geo_audit_loop.agents._parsing import extract_json_object, page_features
from geo_audit_loop.config import constants as c
from geo_audit_loop.domain.audit import AuditFinding, AuditReport, prioritize_findings
from geo_audit_loop.domain.errors import ReasoningError
from geo_audit_loop.domain.findings import TopFlopReport
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.probe import ProbeUsage
from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningResult, ReasoningStatus
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.domain.templates import PatternReport
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.ports.reasoning import ReasoningPort

_AGENT: Final = "geo_auditor"
_TASK: Final = "geo_auditor"
_MAX_ATTEMPTS: Final = 2  # ein Reasoning-Aufruf + ein Retry bei Schema-/Parse-Fehler


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GeoAuditorService:
    """Auditiert die Flop-Seiten gegen die Templates und liefert priorisierte ``AuditFinding``s."""

    def __init__(
        self,
        *,
        reasoning: ReasoningPort,
        system_prompt: str,
        prompt_version: str,
        cost_tracker: CostTracker,
        max_tokens: int = c.DEFAULT_MAX_TOKENS,
        temperature: float = c.DEFAULT_TEMPERATURE,
        logger: logging.Logger | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._reasoning = reasoning
        self._system = system_prompt
        self._prompt_version = prompt_version
        self._cost = cost_tracker
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._clock = clock if clock is not None else _utc_now

    def run(
        self,
        run_context: RunContext,
        report: TopFlopReport,
        pages: Seq[PageInventory],
        patterns: PatternReport,
    ) -> AuditReport:
        """Auditiert die Flop-Seiten gegen die Templates und baut den priorisierten AuditReport."""
        by_url = {inv.page.url: inv for inv in pages}
        flop_features = [page_features(by_url[e.url]) for e in report.flop if e.url in by_url]
        prompt = self._build_prompt(flop_features, patterns)
        findings = self._audit(run_context, prompt)
        log_event(
            self._log,
            "audit.done",
            run_id=run_context.run_id,
            agent=_AGENT,
            prompt_version=self._prompt_version,
            n_findings=len(findings),
        )
        return AuditReport(
            run_id=run_context.run_id,
            target_domain=run_context.target_domain,
            generated_at=self._clock(),
            audited_urls=tuple(e.url for e in report.flop),
            findings=prioritize_findings(findings),
        )

    def _build_prompt(self, flop_features: list[dict[str, object]], patterns: PatternReport) -> str:
        templates_brief = [
            {
                "template_id": t.template_id,
                "title": t.title,
                "summary": t.summary,
                "levers": [lever.value for lever in t.levers],
                "criteria": list(t.criteria),
            }
            for t in patterns.templates
        ]
        return (
            "Best-Practice-Templates der Top-Seiten:\n"
            f"{json.dumps(templates_brief, ensure_ascii=False, indent=2)}\n\n"
            "Flop-Seiten (selten/nie zitiert) mit On-Page-Inventar:\n"
            f"{json.dumps(flop_features, ensure_ascii=False, indent=2)}\n\n"
            "Benenne pro Flop-Seite die konkreten Schwachstellen als Findings, jeweils mit "
            "Beleg, Hebel, Pyramide-Ebene, Schweregrad und Empfehlung. Gib NUR das JSON-Objekt "
            "zurueck."
        )

    def _audit(self, run_context: RunContext, prompt: str) -> tuple[AuditFinding, ...]:
        last_error = "kein Versuch ausgefuehrt"
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            self._cost.ensure_within_budget()
            result = self._reasoning.reason(self._request(run_context, prompt))
            self._record(result)
            if result.status is ReasoningStatus.ERROR:
                last_error = result.error or "Reasoning-Fehler"
            else:
                try:
                    return self._parse(result.text)
                except (ReasoningError, ValidationError) as exc:
                    last_error = str(exc)
            log_event(
                self._log,
                "audit.retry",
                run_id=run_context.run_id,
                agent=_AGENT,
                attempt=attempt,
                error=last_error,
                level=logging.WARNING,
            )
        raise ReasoningError(
            f"GEO-Audit fehlgeschlagen nach {_MAX_ATTEMPTS} Versuchen: {last_error}"
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

    def _parse(self, text: str) -> tuple[AuditFinding, ...]:
        data = extract_json_object(text)
        raw = data.get("findings")
        if not isinstance(raw, list):
            raise ReasoningError("Reasoning-JSON enthaelt kein 'findings'-Array")
        findings = tuple(AuditFinding.model_validate(item) for item in raw)
        if not findings:
            raise ReasoningError("keine Findings extrahiert")
        return findings
