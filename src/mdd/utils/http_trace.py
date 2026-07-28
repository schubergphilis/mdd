"""Shared httpx event-hook helpers for request/response trace logging.

Both the Confluence and Lucid REST clients want the same trace output:
log every request at TRACE, log every response at TRACE (plus DEBUG for
4xx/5xx), mask sensitive headers, and optionally dump bodies when
``MDD_TRACE_BODIES=1`` (or ``--trace-bodies``) is set.

Use as::

    httpx.Client(event_hooks=make_event_hooks(get_logger("mdd.foo")))
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import TYPE_CHECKING

from mdd.utils.logging import TRACE

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    import httpx

# Max bytes of request/response body to dump when body tracing is enabled.
# Storage-format payloads can be MB-sized; truncating keeps the trace usable.
_BODY_TRUNCATE_BYTES = 4096

# Headers that are either secrets or PII — never log their values, just whether
# they're set and a short fingerprint so we can correlate without leaking.
_SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "set-cookie", "proxy-authorization"})


def trace_bodies_enabled() -> bool:
    """Return True if request/response body tracing is enabled.

    Set ``MDD_TRACE_BODIES=1`` (or pass ``--trace-bodies`` to the CLI) to
    enable. Bodies are truncated to ``_BODY_TRUNCATE_BYTES`` so a 5 MB
    payload doesn't fill the terminal.
    """
    return os.environ.get("MDD_TRACE_BODIES", "").lower() in ("1", "true", "yes", "on")


def format_body(raw: bytes | str) -> str:
    """Format a body for logging: decode to str if needed, truncate, replace newlines."""
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return f"<{len(raw)} bytes of binary data>"
    else:
        text = raw
    if len(text) > _BODY_TRUNCATE_BYTES:
        return text[:_BODY_TRUNCATE_BYTES] + f"…[+{len(text) - _BODY_TRUNCATE_BYTES} more chars]"
    return text


def format_headers(headers: httpx.Headers) -> str:
    """Render httpx headers for the trace, masking sensitive values.

    For sensitive headers we show only the scheme prefix (e.g. ``Basic`` /
    ``Bearer``) and an SHA-256 fingerprint of the value so two calls with
    the same token can be correlated without exposing the secret.
    """
    lines: list[str] = []
    for name, value in headers.items():
        if name.lower() in _SENSITIVE_HEADERS:
            scheme = value.split(" ", 1)[0] if " " in value else "(set)"
            fp = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:8]
            lines.append(f"  {name}: {scheme} <masked sha256:{fp}>")
        else:
            lines.append(f"  {name}: {value}")
    return "\n".join(lines)


def _log_request_headers_and_body(log: logging.Logger, request: httpx.Request) -> None:
    log.log(
        TRACE,
        "HTTP %s %s request headers:\n%s",
        request.method,
        request.url,
        format_headers(request.headers),
    )
    if request.content:
        log.log(
            TRACE,
            "HTTP %s %s body:\n%s",
            request.method,
            request.url,
            format_body(request.content),
        )


def make_event_hooks(
    log: logging.Logger,
) -> dict[str, list[Callable[..., None]]]:
    """Build httpx ``event_hooks`` that log requests/responses via *log*.

    Stashes a start timestamp on ``request.extensions`` so the response hook
    can report elapsed time. ``Response.elapsed`` is *not* available inside
    an event hook — it raises ``RuntimeError`` until the body is read.
    """

    def log_request(request: httpx.Request) -> None:
        request.extensions["mdd_start"] = time.monotonic()
        log.log(TRACE, "HTTP %s %s", request.method, request.url)
        if trace_bodies_enabled():
            _log_request_headers_and_body(log, request)

    def log_response(response: httpx.Response) -> None:
        request = response.request
        start = request.extensions.get("mdd_start")
        elapsed_ms = (time.monotonic() - start) * 1000 if isinstance(start, float) else 0.0
        log.log(
            TRACE,
            "HTTP %s %s -> %d (%.0f ms)",
            request.method,
            request.url,
            response.status_code,
            elapsed_ms,
        )
        if response.status_code >= 400:
            log.debug(
                "HTTP %s %s -> %d (%.0f ms)",
                request.method,
                request.url,
                response.status_code,
                elapsed_ms,
            )
        if trace_bodies_enabled():
            log.log(
                TRACE,
                "HTTP %s %s response headers:\n%s",
                request.method,
                request.url,
                format_headers(response.headers),
            )

    return {"request": [log_request], "response": [log_response]}
