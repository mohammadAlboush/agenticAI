"""Pattern-Miner-Agent: extrahiert Best-Practice-Templates aus den Top-Seiten (LLM-getrieben).

Nimmt den Top/Flop-Report + das Seiten-Inventar, baut aus den Top-Seiten einen Prompt,
ruft den ``ReasoningPort`` und parst die Antwort in ``Template``s. Haengt nur an domain,
ports, prompts-Text und observability -- nie an einem konkreten LLM-SDK. Budget wird ueber
den ``CostTracker`` erzwungen (analog Sampler); bei Schema-Fehlern begrenzt erneut versucht.
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
from geo_audit_loop.domain.errors import ReasoningError
from geo_audit_loop.domain.findings import TopFlopReport
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.probe import ProbeUsage
from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningResult, ReasoningStatus
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.domain.templates import PatternReport, Template
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.ports.reasoning import ReasoningPort
from geo_audit_loop.ports.storage import StoragePort

_AGENT: Final = "pattern_miner"
_TASK: Final = "pattern_miner"
_MAX_ATTEMPTS: Final = 2  # ein Reasoning-Aufruf + ein Retry bei Schema-/Parse-Fehler

# JSON-Schema fuer Tool-Use (Live-Claude erzwingt damit valide Ausgabe; Mock ignoriert es).
_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "templates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "template_id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "levers": {"type": "array", "items": {"type": "string"}},
                    "pyramid_level": {"type": "string"},
                    "criteria": {"type": "array", "items": {"type": "string"}},
                    "evidence_urls": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "template_id",
                    "title",
                    "summary",
                    "levers",
                    "pyramid_level",
                    "confidence",
                ],
            },
        }
    },
    "required": ["templates"],
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PatternMinerService:
    """Mint aus den Top-Seiten wiederverwendbare ``Template``s (erfuellt die Agenten-Regeln)."""

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
        self, run_context: RunContext, report: TopFlopReport, pages: Seq[PageInventory]
    ) -> PatternReport:
        """Leitet aus den Top-Seiten des Reports die Templates ab und baut den PatternReport."""
        by_url = {inv.page.url: inv for inv in pages}
        # Sprint 6: jede Top-Seite traegt ihr statistisches Sichtbarkeits-Band -> der Miner
        # kann Muster bevorzugt aus belastbar ueberdurchschnittlichen Seiten ableiten.
        top_features = [
            {**page_features(by_url[e.url]), "visibility_band": e.band.value}
            for e in report.top
            if e.url in by_url
        ]
        prompt = self._build_prompt(top_features)
        templates = self._mine(run_context, prompt)
        log_event(
            self._log,
            "pattern.mined",
            run_id=run_context.run_id,
            agent=_AGENT,
            prompt_version=self._prompt_version,
            n_templates=len(templates),
        )
        return PatternReport(
            run_id=run_context.run_id,
            target_domain=run_context.target_domain,
            generated_at=self._clock(),
            source_urls=tuple(e.url for e in report.top),
            templates=templates,
        )

    def _build_prompt(self, top_features: list[dict[str, object]]) -> str:
        payload = json.dumps(top_features, ensure_ascii=False, indent=2)
        return (
            "Top-Seiten (in AI-Engines erfolgreich zitiert) mit On-Page-Inventar. Das Feld "
            "'visibility_band' gibt die statistische Absetzung an: 'above_field' = belastbar "
            "ueberdurchschnittlich zitiert, 'typical' = statistisch nicht vom Domain-Schnitt "
            "unterscheidbar (schwaecherer Beleg):\n"
            f"{payload}\n\n"
            "Leite 2-5 wiederverwendbare Templates ab, die erklaeren, warum diese Seiten "
            "zitiert werden; stuetze dich bevorzugt auf 'above_field'-Seiten. "
            "Gib NUR das JSON-Objekt zurueck."
        )

    def _mine(self, run_context: RunContext, prompt: str) -> tuple[Template, ...]:
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
                "pattern.retry",
                run_id=run_context.run_id,
                agent=_AGENT,
                attempt=attempt,
                error=last_error,
                level=logging.WARNING,
            )
        raise ReasoningError(
            f"Pattern-Mining fehlgeschlagen nach {_MAX_ATTEMPTS} Versuchen: {last_error}"
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

    def _parse(self, text: str, run_id: str) -> tuple[Template, ...]:
        data = extract_json_object(text)
        raw = data.get("templates")
        if not isinstance(raw, list):
            raise ReasoningError("Reasoning-JSON enthaelt kein 'templates'-Array")
        templates: list[Template] = []
        for item in raw:  # pro Item validieren: gueltige behalten, ungueltige loggen
            try:
                templates.append(Template.model_validate(item))
            except ValidationError as exc:
                log_event(
                    self._log,
                    "pattern.item_dropped",
                    run_id=run_id,
                    agent=_AGENT,
                    error=str(exc),
                    level=logging.WARNING,
                )
        if not templates:
            raise ReasoningError("keine gueltigen Templates extrahiert")
        return tuple(templates)
