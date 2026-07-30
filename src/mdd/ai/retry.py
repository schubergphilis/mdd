"""Retry decorator with Retry-After header support."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, NoReturn

import openai

from mdd.ai.models import AiRateLimitedError, AiServerError

# 5 attempts: 1 initial + 4 retries.
_BASE_DELAYS = (1.0, 2.0, 4.0, 8.0)
RETRY_AFTER_CAP = 60.0
_JITTER_FRACTION = 0.1


def _parse_retry_after(exc: openai.RateLimitError) -> float | None:
    """Extract the Retry-After value (seconds) from the exception, if present."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers: Any = getattr(response, "headers", None)  # pyright: ignore[reportAny]
    if headers is None:
        return None
    value: Any = None  # pyright: ignore[reportAny]
    # headers can be a mapping; try case-insensitive lookup
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")  # pyright: ignore[reportAny]
    except Exception:
        return None
    if value is None:
        return None
    try:
        return min(float(value), RETRY_AFTER_CAP)
    except ValueError, TypeError:
        return None


def _jitter(delay: float) -> float:
    return delay + random.uniform(0, delay * _JITTER_FRACTION)  # noqa: S311  # backoff jitter, not crypto


def _classify_retryable(exc: Exception, base_delay: float) -> tuple[bool, float]:
    """Classify a retryable exception and compute the sleep seconds.

    Returns ``(is_rate_limit, sleep_seconds)``. Re-raises exceptions that should
    NOT be retried (auth errors, 4xx other than 429), so callers see only
    retry-eligible failures here. RateLimitError honours the ``Retry-After``
    header (capped); 5xx and APIConnectionError use the exponential backoff
    delay. Non-retryable exception types are not handled here — the caller
    relies on Python's default propagation for those.
    """
    if isinstance(exc, openai.AuthenticationError):
        raise exc
    if isinstance(exc, openai.RateLimitError):
        retry_after = _parse_retry_after(exc)
        return True, _jitter(retry_after if retry_after is not None else base_delay)
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code < 500:
            raise exc
        return False, _jitter(base_delay)
    if isinstance(exc, openai.APIConnectionError):
        return False, _jitter(base_delay)
    raise exc


_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    openai.AuthenticationError,
    openai.RateLimitError,
    openai.APIStatusError,
    openai.APIConnectionError,
)


def _raise_exhausted(is_rate_limit: bool, last_exc: Exception | None, attempts: int) -> NoReturn:
    """Raise the appropriate terminal error after all retries are spent."""
    if is_rate_limit:
        raise AiRateLimitedError(
            f"AI rate limit persisted after {attempts} attempts. "
            "Try again later or reduce concurrency (ai.concurrency in config)."
        ) from last_exc
    raise AiServerError(f"AI server error persisted after {attempts} attempts.") from last_exc


def with_retry[F: Callable[..., Any]](fn: F) -> F:  # pyright: ignore[reportAny]
    """Wrap *fn* with exponential backoff + Retry-After honouring.

    Retries on:
    - openai.RateLimitError (429)
    - openai.APIStatusError with status >= 500
    - openai.APIConnectionError

    After all retries exhausted, raises AiRateLimitedError or AiServerError.
    """

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportAny]
        last_exc: Exception | None = None
        is_rate_limit = False
        for delay in (*_BASE_DELAYS, None):
            try:
                return fn(*args, **kwargs)
            except _RETRYABLE_EXCEPTIONS as exc:
                is_rate_limit, sleep_time = _classify_retryable(exc, float(delay or 0.0))
                last_exc = exc
                if delay is None:
                    break
                time.sleep(sleep_time)

        _raise_exhausted(is_rate_limit, last_exc, attempts=len(_BASE_DELAYS) + 1)

    return wrapper  # pyright: ignore[reportReturnType]
