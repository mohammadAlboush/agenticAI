"""Query-Generator-Agent (Session 4, LLM): fuellt Blind-Spot-Intents mit neuen Fragen.

Nimmt den deterministischen ``CoverageReport`` (welche Fragetypen sind schwach abgedeckt?)
und laesst den ``ReasoningPort`` je schwachem Intent realistische Nutzer-Fragen formulieren —
die konkreten Luecken-Fragen, mit denen die Domain unsichtbare Intents adressieren kann.
Haengt nur an domain, ports, prompts-Text und observability, nie an einem LLM-SDK. Budget
ueber den ``CostTracker`` (analog Pattern-Miner); bei Schema-Fehlern begrenzt erneut versucht.
Nicht-deterministisch (LLM) -> versionierter Prompt + Eval-Slot statt Golden-Gleichheit.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Final

from pydantic import ValidationError

from geo_audit_loop.agents._parsing import extract_json_object
from geo_audit_loop.config import constants as c
from geo_audit_loop.domain.coverage import CoverageReport, GeneratedQuery
from geo_audit_loop.domain.errors import ReasoningError
from geo_audit_loop.domain.probe import ProbePrompt, ProbeUsage, QueryIntent
from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningResult, ReasoningStatus
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.ports.reasoning import ReasoningPort
from geo_audit_loop.ports.storage import StoragePort

_AGENT: Final = "query_generator"
_TASK: Final = c.QUERY_GENERATOR_TASK
_MAX_ATTEMPTS: Final = 2  # ein Reasoning-Aufruf + ein Retry bei Schema-/Parse-Fehler

# JSON-Schema fuer Tool-Use (Live-Claude erzwingt damit valide Ausgabe; Mock ignoriert es).
_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["intent", "text"],
            },
        }
    },
    "required": ["queries"],
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class QueryGeneratorService:
    """Erzeugt je schwachem Intent Luecken-Fragen (erfuellt die Agenten-Regeln)."""

    def __init__(
        self,
        *,
        reasoning: ReasoningPort,
        system_prompt: str,
        prompt_version: str,
        cost_tracker: CostTracker,
        prompts: Sequence[ProbePrompt],
        max_per_intent: int = c.QUERY_GENERATOR_MAX_PER_INTENT,
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
        self._max_per_intent = max_per_intent
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._storage = storage
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._clock = clock if clock is not None else _utc_now
        # Beispiel-Prompts je Intent (fuer den Stil-Kontext im Prompt).
        self._examples: dict[QueryIntent, list[str]] = defaultdict(list)
        for prompt in prompts:
            if prompt.intent is not None:
                self._examples[prompt.intent].append(prompt.text)

    def run(self, run_context: RunContext, coverage: CoverageReport) -> tuple[GeneratedQuery, ...]:
        """Erzeugt Luecken-Fragen fuer die schwachen Intents des Coverage-Reports.

        Ohne schwache Intents (keine Blind Spots) wird KEIN LLM-Aufruf gemacht -> leeres
        Ergebnis, kein Budget-Verbrauch. Sonst: ein Reasoning-Aufruf, die Antwort wird in
        ``GeneratedQuery`` geparst und auf die angeforderten Intents gefiltert.
        """
        weak = tuple(coverage.weakest_intents)
        if not weak:
            return ()
        prompt = self._build_prompt(weak)
        queries = self._generate(run_context, prompt, frozenset(weak))
        log_event(
            self._log,
            "query_generator.done",
            run_id=run_context.run_id,
            agent=_AGENT,
            prompt_version=self._prompt_version,
            n_weak_intents=len(weak),
            n_queries=len(queries),
        )
        return queries

    def _build_prompt(self, weak: tuple[QueryIntent, ...]) -> str:
        blocks = []
        for intent in weak:
            examples = self._examples.get(intent, [])
            sample = examples[0] if examples else "(kein Beispiel im aktuellen Set)"
            blocks.append({"intent": intent.value, "beispiel_frage": sample})
        payload = json.dumps(blocks, ensure_ascii=False, indent=2)
        return (
            "Schwach abgedeckte Intents (Blind Spots) dieser IT-Sicherheits-Domain, "
            "mit je einer Beispiel-Frage zum Stil:\n"
            f"{payload}\n\n"
            f"Formuliere bis zu {self._max_per_intent} neue Nutzer-Fragen JE schwachem Intent "
            "(nur fuer die oben gelisteten Intents). Gib NUR das JSON-Objekt zurueck."
        )

    def _generate(
        self, run_context: RunContext, prompt: str, weak: frozenset[QueryIntent]
    ) -> tuple[GeneratedQuery, ...]:
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
                    return self._parse(result.text, weak, run_context.run_id)
                except (ReasoningError, ValidationError) as exc:
                    last_error = str(exc)
            log_event(
                self._log,
                "query_generator.retry",
                run_id=run_context.run_id,
                agent=_AGENT,
                attempt=attempt,
                error=last_error,
                level=logging.WARNING,
            )
        raise ReasoningError(
            f"Query-Generierung fehlgeschlagen nach {_MAX_ATTEMPTS} Versuchen: {last_error}"
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

    def _parse(
        self, text: str, weak: frozenset[QueryIntent], run_id: str
    ) -> tuple[GeneratedQuery, ...]:
        """Parst die Antwort, behaelt nur angeforderte Intents, cappt + dedupliziert.

        Fragen ausserhalb der schwachen Intent-Menge werden verworfen (der Generator soll nur
        Blind Spots fuellen); je Intent bleiben hoechstens ``max_per_intent``; Dubletten (per
        Text, case-insensitiv) fliegen raus. Reihenfolge der Antwort bleibt erhalten.
        """
        data = extract_json_object(text)
        raw = data.get("queries")
        if not isinstance(raw, list):
            raise ReasoningError("Reasoning-JSON enthaelt kein 'queries'-Array")
        kept: list[GeneratedQuery] = []
        per_intent: dict[QueryIntent, int] = defaultdict(int)
        seen: set[str] = set()
        for item in raw:  # pro Item validieren: gueltige/passende behalten, sonst loggen
            try:
                query = GeneratedQuery.model_validate(item)
            except ValidationError as exc:
                log_event(
                    self._log,
                    "query_generator.item_dropped",
                    run_id=run_id,
                    agent=_AGENT,
                    error=str(exc),
                    level=logging.WARNING,
                )
                continue
            key = query.text.strip().lower()
            if query.intent not in weak or key in seen:
                continue
            if per_intent[query.intent] >= self._max_per_intent:
                continue
            seen.add(key)
            per_intent[query.intent] += 1
            kept.append(query)
        if not kept:
            raise ReasoningError("keine gueltigen Luecken-Fragen fuer die schwachen Intents")
        return tuple(kept)
