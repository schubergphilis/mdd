"""Test-isolation helpers for tests/lucid.

Two effects of running the ``mdd`` CLI inside another test linger across
test boundaries and break later tests, now that status output is routed
through :mod:`logging` instead of ``print``:

1. :func:`mdd.utils.logging.configure` attaches a
   :class:`logging.StreamHandler` bound to the ``sys.stderr`` of the
   moment. When that stream is the captured stream from an earlier
   ``capsys``-using test, subsequent log emits raise
   ``ValueError: I/O operation on closed file``.

2. ``configure()`` sets ``propagate = False`` on the ``mdd`` logger so
   it doesn't double-print through the stdlib root logger. With
   propagation disabled, pytest's ``caplog`` (which attaches its
   handler to the root logger) cannot capture ``mdd.*`` records.

The fixture below scrubs both: it strips non-Null handlers from the
``mdd`` logger and re-enables propagation around each test, so ``caplog``
captures records and stale stderr handlers can't fire.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


def _scrub_mdd_logger() -> None:
    """Strip non-Null handlers and re-enable propagation on the ``mdd`` logger."""
    root = logging.getLogger("mdd")
    for handler in list(root.handlers):
        if not isinstance(handler, logging.NullHandler):
            root.removeHandler(handler)
    root.propagate = True


@pytest.fixture(autouse=True)
def _reset_mdd_logger() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Reset the ``mdd`` root logger around each test (see module docstring)."""
    _scrub_mdd_logger()
    try:
        yield
    finally:
        _scrub_mdd_logger()
