"""Phase-3-Gate: Retry mit Backoff (deterministisch, injizierter sleep)."""

from __future__ import annotations

import pytest

from geo_audit_loop.observability.retry import retry_call


def test_succeeds_after_transient_failures() -> None:
    attempts = {"n": 0}
    delays: list[float] = []

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("transient")
        return "ok"

    result = retry_call(
        flaky,
        max_attempts=5,
        base_delay_s=1.0,
        max_delay_s=10.0,
        retry_on=(ValueError,),
        sleep=delays.append,
    )
    assert result == "ok"
    assert attempts["n"] == 3
    assert delays == [1.0, 2.0]  # exponentiell: 1, 2


def test_exhausts_attempts_then_raises() -> None:
    def always_fail() -> str:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        retry_call(
            always_fail,
            max_attempts=3,
            base_delay_s=0.5,
            max_delay_s=2.0,
            retry_on=(ValueError,),
            sleep=lambda _d: None,
        )


def test_does_not_retry_unlisted_exception() -> None:
    calls = {"n": 0}

    def fail_key() -> str:
        calls["n"] += 1
        raise KeyError("k")

    with pytest.raises(KeyError):
        retry_call(
            fail_key,
            max_attempts=3,
            base_delay_s=0.1,
            max_delay_s=1.0,
            retry_on=(ValueError,),
            sleep=lambda _d: None,
        )
    assert calls["n"] == 1  # kein Retry


def test_backoff_is_capped() -> None:
    delays: list[float] = []

    def always_fail() -> str:
        raise ValueError("x")

    with pytest.raises(ValueError, match="x"):
        retry_call(
            always_fail,
            max_attempts=5,
            base_delay_s=10.0,
            max_delay_s=15.0,
            retry_on=(ValueError,),
            sleep=delays.append,
        )
    # Rohwerte 10, 20, 40, 80 -> gedeckelt auf 15
    assert delays == [10.0, 15.0, 15.0, 15.0]
