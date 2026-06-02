"""Begrenzter Retry mit exponentiellem Backoff (keine externe Dependency, Projektregeln §6)."""

from __future__ import annotations

import time
from collections.abc import Callable

OnRetry = Callable[[int, Exception, float], None]


def retry_call[T](
    func: Callable[[], T],
    *,
    max_attempts: int,
    base_delay_s: float,
    max_delay_s: float,
    retry_on: tuple[type[Exception], ...],
    on_retry: OnRetry | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Ruft ``func`` auf und wiederholt bei ``retry_on`` mit exponentiellem Backoff.

    Backoff: ``min(base_delay_s * 2**(versuch-1), max_delay_s)``. Nach Ausschoepfen
    aller Versuche wird die letzte Ausnahme erneut geworfen. ``sleep`` und ``on_retry``
    sind injizierbar (Tests, Logging).
    """
    if max_attempts < 1:
        raise ValueError("max_attempts muss >= 1 sein")

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except retry_on as exc:
            last_exc = exc
            if attempt == max_attempts:
                break
            delay = min(base_delay_s * (2 ** (attempt - 1)), max_delay_s)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            sleep(delay)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry_call: unerreichbarer Zustand")  # pragma: no cover
