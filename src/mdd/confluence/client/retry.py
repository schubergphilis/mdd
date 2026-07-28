"""Retry-decision helpers for the Confluence client."""

from __future__ import annotations

import datetime
import email.utils
import random
from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


# Cap honoured Retry-After at 60 s so a server-suggested 10-minute pause does
# not freeze the caller (spec S16).
_RETRY_AFTER_CAP_SECONDS = 60.0


def should_retry(response: httpx.Response) -> bool:
    return response.status_code in (429, 503) or response.status_code >= 500


def jittered_delay(delay: float) -> float:
    """Return ``delay`` with up to 10 % positive jitter (spec S09).

    Jitter avoids lockstep retry storms when several processes hit the same
    rate-limit window simultaneously.
    """
    return delay + random.uniform(0, delay * 0.1)  # noqa: S311  # backoff jitter, not crypto


def backoff_for_response(response: httpx.Response, scheduled_delay: float) -> float:
    """Return the sleep duration before retrying *response*.

    For a 429 carrying a parseable ``Retry-After`` header, honour the header
    (capped at 60 s, spec S16). Otherwise use ``scheduled_delay`` with jitter.
    """
    if response.status_code == 429:
        retry_after = parse_retry_after(response)
        if retry_after is not None:
            return min(retry_after, _RETRY_AFTER_CAP_SECONDS)
    return jittered_delay(scheduled_delay)


def parse_retry_after(response: httpx.Response) -> float | None:
    """Return the Retry-After header value in seconds, or None if absent/unparseable.

    Handles both integer-seconds form ("30") and HTTP-date form per RFC 9110.
    """
    header = response.headers.get("Retry-After")
    if not header:
        return None
    header = header.strip()
    # Try integer seconds first
    with suppress(ValueError):
        return float(header)
    # Try HTTP-date form
    try:
        parsed = email.utils.parsedate_to_datetime(header)
        now = datetime.datetime.now(tz=datetime.UTC)
        delta = (parsed - now).total_seconds()
        return max(0.0, delta)
    except Exception:
        return None
