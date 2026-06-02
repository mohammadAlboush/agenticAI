"""Phase-1-Gate: Validierung und Unveraenderlichkeit der Domaenen-Contracts."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from geo_audit_loop.domain.errors import BudgetExceeded
from geo_audit_loop.domain.probe import Citation, EngineId, ProbeRequest
from geo_audit_loop.domain.run import RunRecord, RunStatus

FIXED = datetime(2026, 1, 1, 12, 0, 0)


def _make_request(*, temperature: float = 0.5, max_tokens: int = 512) -> ProbeRequest:
    """Baut einen gueltigen ProbeRequest; einzelne Felder fuer Grenzwert-Tests ueberschreibbar."""
    return ProbeRequest(
        run_id="run-1",
        engine_id=EngineId.PERPLEXITY,
        prompt_id="p1",
        prompt_text="Was ist NIS2?",
        prompt_version="v1",
        model="sonar-pro",
        target_domain="it-sicherheit.de",
        max_tokens=max_tokens,
        temperature=temperature,
    )


def test_citation_requires_url() -> None:
    with pytest.raises(ValidationError):
        Citation(url="", engine=EngineId.PERPLEXITY)


def test_citation_rank_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Citation(url="https://x.de", engine=EngineId.CLAUDE, rank=0)


def test_models_are_frozen() -> None:
    cite = Citation(url="https://x.de", engine=EngineId.CLAUDE)
    with pytest.raises(ValidationError):
        cite.url = "https://y.de"


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        Citation(url="https://x.de", engine=EngineId.CLAUDE, bogus=1)  # type: ignore[call-arg]


def test_probe_request_accepts_valid_bounds() -> None:
    req = _make_request(temperature=0.0)
    assert req.engine_id is EngineId.PERPLEXITY
    assert req.search_mode is None


def test_probe_request_rejects_temperature_out_of_range() -> None:
    with pytest.raises(ValidationError):
        _make_request(temperature=2.5)


def test_probe_request_rejects_nonpositive_max_tokens() -> None:
    with pytest.raises(ValidationError):
        _make_request(max_tokens=0)


def test_run_record_defaults_and_copy() -> None:
    rec = RunRecord(
        run_id="run-1",
        target_domain="it-sicherheit.de",
        status=RunStatus.RUNNING,
        started_at=FIXED,
        seed=42,
        prompt_set_version="v1",
        config_hash="abc",
    )
    assert rec.total_probes == 0
    assert rec.status is RunStatus.RUNNING
    done = rec.model_copy(update={"status": RunStatus.COMPLETED, "total_probes": 240})
    assert done.status is RunStatus.COMPLETED
    assert done.total_probes == 240
    assert rec.status is RunStatus.RUNNING  # Original unveraendert (frozen)


def test_budget_exceeded_carries_context() -> None:
    err = BudgetExceeded("zu viele Probes", limit_name="max_probes", limit=240, used=241)
    assert err.limit_name == "max_probes"
    assert err.limit == 240
    assert err.used == 241
