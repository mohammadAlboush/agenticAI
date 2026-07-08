"""Entity-Extractor-Agent (Session 8, LLM): findet sameAs-Autoritaets-Quellen der Marke.

Nimmt den deterministischen ``EntityGraphReport`` (Marke + deklarierte Typen) plus etwas
Seiten-Kontext und laesst den ``ReasoningPort`` externe Autoritaets-URLs (Wikipedia/Wikidata,
Register, verifizierte Profile) vorschlagen, auf die das Organization-Schema per ``sameAs``
verweisen sollte — die konkrete semantische Verfeinerung des JSON-LD-Fixes. Haengt nur an
domain, ports, prompts-Text und observability, nie an einem LLM-SDK. Budget ueber den
``CostTracker``; bei Schema-Fehlern begrenzt erneut versucht. Nicht-deterministisch (LLM)
-> versionierter Prompt + Eval-Slot. Eine leere (aber valide) Antwort ist erlaubt.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Final

from geo_audit_loop.agents._parsing import extract_json_object
from geo_audit_loop.config import constants as c
from geo_audit_loop.domain.entity import EntityGraphReport
from geo_audit_loop.domain.errors import ReasoningError
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.probe import ProbeUsage
from geo_audit_loop.domain.reasoning import ReasoningRequest, ReasoningResult, ReasoningStatus
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.cost import CostTracker
from geo_audit_loop.observability.logging import log_event
from geo_audit_loop.ports.reasoning import ReasoningPort
from geo_audit_loop.ports.storage import StoragePort

_AGENT: Final = "entity_extractor"
_TASK: Final = c.ENTITY_EXTRACTOR_TASK
_MAX_ATTEMPTS: Final = 2  # ein Reasoning-Aufruf + ein Retry bei Schema-/Parse-Fehler
_CONTEXT_PAGES: Final = 3  # so viele Seitentitel gehen als Kontext in den Prompt

# JSON-Schema fuer Tool-Use (Live-Claude erzwingt damit valide Ausgabe; Mock ignoriert es).
_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "same_as": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["same_as"],
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _is_absolute_url(value: object) -> bool:
    """Nur absolute http(s)-URLs sind valide sameAs-Ziele (keine relativen Pfade/Namen)."""
    return isinstance(value, str) and (value.startswith("https://") or value.startswith("http://"))


class EntityExtractorService:
    """Schlaegt sameAs-Autoritaets-URLs fuer die Marke vor (erfuellt die Agenten-Regeln)."""

    def __init__(
        self,
        *,
        reasoning: ReasoningPort,
        system_prompt: str,
        prompt_version: str,
        cost_tracker: CostTracker,
        max_same_as: int = c.ENTITY_EXTRACTOR_MAX_SAME_AS,
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
        self._max_same_as = max_same_as
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._storage = storage
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._clock = clock if clock is not None else _utc_now

    def run(
        self,
        run_context: RunContext,
        graph: EntityGraphReport,
        pages: Sequence[PageInventory],
    ) -> tuple[str, ...]:
        """Liefert bis zu ``max_same_as`` validierte sameAs-URLs der Marke (ggf. leer).

        Eine leere, aber schema-valide Antwort ist ein legitimes Ergebnis (keine Quelle
        gefunden) und loest KEINEN Retry aus; nur fehlendes/kaputtes JSON wird erneut versucht.
        """
        prompt = self._build_prompt(graph, pages)
        same_as = self._extract(run_context, prompt)
        log_event(
            self._log,
            "entity_extractor.done",
            run_id=run_context.run_id,
            agent=_AGENT,
            prompt_version=self._prompt_version,
            brand=graph.brand_name,
            n_same_as=len(same_as),
        )
        return same_as

    def _build_prompt(self, graph: EntityGraphReport, pages: Sequence[PageInventory]) -> str:
        titles = [p.page.title for p in pages[:_CONTEXT_PAGES] if p.page.title]
        context = {
            "marke": graph.brand_name,
            "domain": graph.target_domain,
            "beispiel_seitentitel": titles,
        }
        payload = json.dumps(context, ensure_ascii=False, indent=2)
        return (
            "Organisation/Marke einer Domain mit etwas Seiten-Kontext:\n"
            f"{payload}\n\n"
            f"Nenne bis zu {self._max_same_as} externe Autoritaets-URLs (sameAs), die genau "
            "diese Organisation beschreiben. Gib NUR das JSON-Objekt zurueck."
        )

    def _extract(self, run_context: RunContext, prompt: str) -> tuple[str, ...]:
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
                    return self._parse(result.text)
                except ReasoningError as exc:
                    last_error = str(exc)
            log_event(
                self._log,
                "entity_extractor.retry",
                run_id=run_context.run_id,
                agent=_AGENT,
                attempt=attempt,
                error=last_error,
                level=logging.WARNING,
            )
        raise ReasoningError(
            f"Entity-Extraktion fehlgeschlagen nach {_MAX_ATTEMPTS} Versuchen: {last_error}"
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

    def _parse(self, text: str) -> tuple[str, ...]:
        """Behaelt nur absolute http(s)-URLs, dedupliziert und cappt (Reihenfolge erhalten).

        ``same_as`` MUSS eine Liste sein (sonst Retry); ungueltige Eintraege (relative Pfade,
        Nicht-Strings) und Dubletten fallen still raus. Eine leere Liste ist erlaubt.
        """
        data = extract_json_object(text)
        raw = data.get("same_as")
        if not isinstance(raw, list):
            raise ReasoningError("Reasoning-JSON enthaelt kein 'same_as'-Array")
        kept: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not _is_absolute_url(item) or item in seen:
                continue
            seen.add(item)
            kept.append(item)
            if len(kept) >= self._max_same_as:
                break
        return tuple(kept)
