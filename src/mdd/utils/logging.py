"""Lightweight logging helper for mdd.

Wraps the stdlib :mod:`logging` module so the rest of the codebase can do::

    from mdd.utils.logging import get_logger

    log = get_logger(__name__)
    log.info("starting export")
    log.trace("GET %s -> %d", url, status)

Design notes:

* A single ``mdd`` root logger is configured on first call to
  :func:`configure`.  All ``mdd.<submodule>`` loggers inherit from it.
* TRACE (level 5) is added below DEBUG (10) for very-verbose request/response
  tracing, which is too noisy to enable at DEBUG.
* Output goes to stderr by default so stdout stays clean for piped commands.
* When the user has not called :func:`configure`, the package logger is given
  a :class:`logging.NullHandler` so library code doesn't print warnings to
  stderr (per the `Python logging tutorial`_ recommendation for libraries).

.. _Python logging tutorial:
   https://docs.python.org/3/howto/logging.html#configuring-logging-for-a-library
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

TRACE: int = 5
"""Custom log level below DEBUG.  Reserved for per-request HTTP tracing."""

_ROOT_NAME = "mdd"
_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"
_configured: bool = False


def _install_trace_level() -> None:
    """Register the TRACE level name and a ``Logger.trace`` convenience method.

    Idempotent — safe to call multiple times.
    """
    if logging.getLevelName(TRACE) != "TRACE":
        logging.addLevelName(TRACE, "TRACE")

    def trace(  # pyright: ignore[reportUnusedFunction]
        self: logging.Logger, message: str, *args: Any, **kwargs: Any
    ) -> None:
        if self.isEnabledFor(TRACE):
            self._log(TRACE, message, args, **kwargs)  # pyright: ignore[reportPrivateUsage]

    if not hasattr(logging.Logger, "trace"):
        logging.Logger.trace = trace  # pyright: ignore[reportAttributeAccessIssue]


_install_trace_level()


def _resolve_level(level: int | str | None) -> int:
    """Coerce a level (int / name / None) to an int log level.

    None falls back to ``MDD_LOG_LEVEL`` env var, then WARNING.
    """
    if level is None:
        env = os.environ.get("MDD_LOG_LEVEL")
        if env:
            level = env
        else:
            return logging.WARNING
    if isinstance(level, int):
        return level
    # str — map name to int.  ``logging.getLevelNamesMapping`` (3.11+) is the
    # non-deprecated way to do this.
    upper = level.upper()
    if upper == "TRACE":
        return TRACE
    mapping = logging.getLevelNamesMapping()
    if upper not in mapping:
        raise ValueError(f"Unknown log level: {level!r}")
    return mapping[upper]


def configure(level: int | str | None = None, *, stream: Any = None) -> logging.Logger:
    """Configure the ``mdd`` root logger.

    Safe to call multiple times — repeated calls only adjust the level and
    do not stack handlers.

    Args:
        level: Log level (int, name like "DEBUG"/"TRACE", or None to use the
            ``MDD_LOG_LEVEL`` env var, defaulting to WARNING).
        stream: Output stream (defaults to ``sys.stderr``).

    Returns:
        The configured ``mdd`` logger.
    """
    global _configured
    target_stream = stream if stream is not None else sys.stderr
    resolved_level = _resolve_level(level)

    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(resolved_level)

    # Replace any prior stream handler so calling configure() twice with a
    # different level updates cleanly.  Keep non-stream handlers (e.g. tests
    # attaching their own).
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.NullHandler):  # pyright: ignore[reportUnknownMemberType]
            root.removeHandler(h)  # pyright: ignore[reportUnknownArgumentType]

    handler = logging.StreamHandler(stream=target_stream)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(handler)
    root.propagate = False
    _configured = True
    return root


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``mdd`` namespace.

    If the caller passes a module name like ``mdd.confluence.client`` it is
    used as-is; otherwise ``mdd.<name>`` is returned.  Library callers that
    pass ``__name__`` get the right thing automatically.

    On first use, a :class:`logging.NullHandler` is attached to the ``mdd``
    root so that emitted records never fall through to the stdlib root logger
    (which prints to stderr at WARNING+).
    """
    root = logging.getLogger(_ROOT_NAME)
    if not root.handlers:
        root.addHandler(logging.NullHandler())
    if name == _ROOT_NAME or name.startswith(_ROOT_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")


def is_configured() -> bool:
    """Return True if :func:`configure` has been called."""
    return _configured
