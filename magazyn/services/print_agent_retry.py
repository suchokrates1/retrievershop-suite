"""Retry i rate limiting dla agenta drukowania."""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable, Deque, Tuple, Type, TypeVar

from .print_agent_errors import ApiError, ShipmentExpiredError

T = TypeVar("T")


def retry_call(
    func: Callable[..., T],
    *args: Any,
    stage: str,
    stop_event,
    retry_metric,
    downtime_metric,
    logger,
    retry_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    max_attempts: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> T:
    """Wykonaj funkcje z exponential backoff i metrykami agenta."""
    attempts = 0
    while True:
        try:
            return func(*args, **kwargs)
        except ShipmentExpiredError:
            raise
        except retry_exceptions as exc:
            attempts += 1
            if attempts >= max_attempts or stop_event.is_set():
                raise
            delay = base_delay * (2 ** (attempts - 1))
            logger.warning(
                "%s failed (%s). Retrying in %.1fs (attempt %s/%s)",
                stage,
                exc,
                delay,
                attempts + 1,
                max_attempts,
            )
            retry_metric.inc()
            downtime_metric.inc(delay)
            if stop_event.wait(delay):
                raise


def enforce_rate_limit(
    *,
    max_calls: int,
    window: float,
    call_times: Deque[float],
    lock,
    stop_event,
    downtime_metric,
    logger,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Ogranicz tempo wywolan API agenta w przesuwanym oknie czasu."""
    if max_calls <= 0 or window <= 0:
        return

    with lock:
        now = monotonic()
        _drop_old_calls(call_times, now, window)
        if len(call_times) >= max_calls:
            wait_until = call_times[0] + window
            wait_time = wait_until - now
            if wait_time > 0:
                logger.debug("Rate limit reached, waiting %.2fs before next API call", wait_time)
                downtime_metric.inc(wait_time)
                if stop_event.wait(wait_time):
                    raise ApiError("Rate limit wait interrupted")
            now = monotonic()
            _drop_old_calls(call_times, now, window)
        call_times.append(monotonic())


def new_call_window() -> Deque[float]:
    """Utworz bufor znacznikow czasu wywolan API."""
    return deque()


def _drop_old_calls(call_times: Deque[float], now: float, window: float) -> None:
    while call_times and now - call_times[0] >= window:
        call_times.popleft()


__all__ = ["enforce_rate_limit", "new_call_window", "retry_call"]