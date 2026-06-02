"""Phase-3-Gate: JSON-Logging gibt run_id und Zusatzfelder strukturiert aus."""

from __future__ import annotations

import json
import logging

from geo_audit_loop.observability.logging import JsonFormatter


def _record(event: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="geo_audit_loop.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=event,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_valid_json_with_core_fields() -> None:
    out = json.loads(JsonFormatter().format(_record("probe.start")))
    assert out["event"] == "probe.start"
    assert out["level"] == "INFO"
    assert out["logger"] == "geo_audit_loop.test"
    assert "ts" in out


def test_formatter_includes_extra_fields() -> None:
    record = _record("probe.done", run_id="run-1", agent="sampler", duration_ms=12)
    out = json.loads(JsonFormatter().format(record))
    assert out["run_id"] == "run-1"
    assert out["agent"] == "sampler"
    assert out["duration_ms"] == 12


def test_formatter_redacts_secret_like_fields() -> None:
    record = _record("probe.start", run_id="r", api_key="pplx-secret", proxy_password="pw")
    out = json.loads(JsonFormatter().format(record))
    assert out["api_key"] == "***redacted***"
    assert out["proxy_password"] == "***redacted***"
    assert out["run_id"] == "r"
