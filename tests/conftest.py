"""Top-level pytest conftest for the mdd test suite.

Ensures the ``mdd`` logger propagates so pytest's ``caplog`` fixture can
capture log records. By default :func:`mdd.utils.logging.configure` sets
``propagate = False`` on the ``mdd`` root so library output doesn't leak
to the stdlib root logger in production, but in tests we want caplog to
work without each test attaching a handler manually (#122).

Also wires the default mirror backend the way the CLI entry point does,
so tests can call the sync engines directly.
"""

from __future__ import annotations

import logging

import pytest

from mdd.mirror.registry import set_default_backend


@pytest.fixture(autouse=True)
def _mdd_logger_propagate() -> None:  # pyright: ignore[reportUnusedFunction]
    """Ensure the ``mdd`` logger propagates so caplog captures its records."""
    logging.getLogger("mdd").propagate = True


@pytest.fixture(autouse=True)
def _mdd_default_backend() -> None:  # pyright: ignore[reportUnusedFunction]
    """Wire the default mirror backend, as :func:`mdd.cli.main` does.

    The sync engines resolve their backend through
    :func:`mdd.mirror.registry.default_backend`, which raises unless an
    entry point has wired one (spec S44 — a stray resolution must be a
    loud error, never a silent fall-through to an unguarded backend).
    Tests call the engines as a library, so they wire it here with the
    same value this project's ``main()`` uses.
    """
    set_default_backend("git")
