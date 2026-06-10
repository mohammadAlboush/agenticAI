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
from typing import Any, Final

from pydantic import ValidationError

from geo_audit_loop.agents._parsing import extract_json_object, page_features
from geo_audit_loop.config import constants as c
from geo_audit_loop.domain.audit import AuditFinding, AuditReport, Severity, prioritize_findings
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
from geo_audit_loop.ports.storage import StoragePort

_AGENT: Final = "geo_auditor"
_TASK: Final = "geo_auditor"
_MAX_ATTEMPTS: Final = 2  # ein Reasoning-Aufruf + ein Retry bei Schema-/Parse-Fehler
_THIN_WORDS: Final = 800  # unter dieser Wortzahl gilt eine Seite als duenn (Severity-Untergrenze)
_SEV_RANK: Final[dict[Severity, int]] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}

# JSON-Schema fuer Tool-Use (Live-Claude erzwingt damit valide Ausgabe; Mock ignoriert es).
_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "target_url": {"type": "string"},
                    "lever": {"type": "string"},
                    "pyramid_level": {"type": "string"},
                    "severity": {"type": "string"},
                    "evidence": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "template_id": {"type": ["string", "null"]},
                },
                "required": [
                    "finding_id",
                    "target_url",
                    "lever",
                    "pyramid_level",
                    "severity",
                    "evidence",
                    "recommendation",
                ],
            },
        }
    },
    "required": ["findings"],
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _apply_severity_floor(
    findings: tuple[AuditFinding, ...], pages_by_url: dict[str, PageInventory]
) -> tuple[AuditFinding, ...]:
    """Hebt die Severity objektiv an: duenne Seite oder fehlendes Autor-Schema => mind. 'medium'.

    Belastbare Inventar-Signale setzen eine Untergrenze und reduzieren so die LLM-Varianz
    (Hybrid-Severity, Sprint 2.1). Rein additiv und deterministisch.
    """
    out: list[AuditFinding] = []
    for finding in findings:
        inv = pages_by_url.get(finding.target_url)
        thin = inv is not None and (
            inv.page.word_count < _THIN_WORDS or not inv.schema_inventory.has_author
        )
        if thin and _SEV_RANK[Severity.MEDIUM] < _SEV_RANK[finding.severity]:
            out.append(finding.model_copy(update={"severity": Severity.MEDIUM}))
        else:
            out.append(finding)
    return tuple(out)


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
        report: TopFlopReport,
        pages: Seq[PageInventory],
        patterns: PatternReport,
    ) -> AuditReport:
        """Auditiert die Flop-Seiten gegen die Templates und baut den priorisierten AuditReport."""
        by_url = {inv.page.url: inv for inv in pages}
        flop_features = [page_features(by_url[e.url]) for e in report.flop if e.url in by_url]
        prompt = self._build_prompt(flop_features, patterns)
        findings = _apply_severity_floor(self._audit(run_context, prompt), by_url)
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

    def _parse(self, text: str, run_id: str) -> tuple[AuditFinding, ...]:
        data = extract_json_object(text)
        raw = data.get("findings")
        if not isinstance(raw, list):
            raise ReasoningError("Reasoning-JSON enthaelt kein 'findings'-Array")
        findings: list[AuditFinding] = []
        for item in raw:  # pro Item validieren: gueltige behalten, ungueltige loggen
            try:
                findings.append(AuditFinding.model_validate(item))
            except ValidationError as exc:
                log_event(
                    self._log,
                    "audit.item_dropped",
                    run_id=run_id,
                    agent=_AGENT,
                    error=str(exc),
                    level=logging.WARNING,
                )
        if not findings:
            raise ReasoningError("keine gueltigen Findings extrahiert")
        return tuple(findings)
