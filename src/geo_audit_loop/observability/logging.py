"""Strukturiertes JSON-Logging mit ``run_id`` (Projektregeln §7).

Ein Log-Eintrag pro Agentenschritt; ``run_id``, ``agent``, ``duration_ms`` und
weitere Felder werden als ``extra`` mitgegeben und landen als JSON-Schluessel.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

# Standard-Attribute eines LogRecord, die NICHT als Extra-Feld ausgegeben werden.
_RESERVED: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
    }
)

# Defense-in-depth: Felder mit secret-verdaechtigem Namen werden im Log redigiert,
# falls versehentlich ein Geheimnis als Extra-Feld durchgereicht wird (Projektregeln §6).
_SECRET_HINTS: tuple[str, ...] = (
    "key",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "credential",
)
_REDACTED = "***redacted***"


class JsonFormatter(logging.Formatter):
    """Formatiert LogRecords als einzeilige JSON-Objekte inkl. Extra-Felder."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialisiert einen LogRecord als einzeilige JSON-Ausgabe."""
        data: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            lowered = key.lower()
            data[key] = _REDACTED if any(hint in lowered for hint in _SECRET_HINTS) else value
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Konfiguriert das Root-Logging auf einen einzelnen JSON-Handler (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Bequemer Zugriff auf einen benannten Logger."""
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    run_id: str,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Loggt ein strukturiertes Ereignis mit ``run_id`` und beliebigen Zusatzfeldern."""
    logger.log(level, event, extra={"run_id": run_id, **fields})


@contextmanager
def step_timer(
    logger: logging.Logger,
    event: str,
    *,
    run_id: str,
    agent: str,
    **fields: Any,
) -> Iterator[None]:
    """Misst die Dauer eines Schritts und loggt sie beim Verlassen als ``duration_ms``."""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = int((time.perf_counter() - start) * 1000)
        log_event(logger, event, run_id=run_id, agent=agent, duration_ms=duration_ms, **fields)
