"""Tests for mdd.mirror.registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mdd.mirror.protocol import EnsureOutcome
from mdd.mirror.registry import BACKENDS, backend_for, register_backend

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from mdd.mirror.protocol import MirrorTarget


class _StubBackend:
    """Minimal MirrorBackend implementation for registry tests."""

    def resolve_remote(self, target: MirrorTarget) -> str | None:
        return None

    def ensure_remote(self, target: MirrorTarget) -> EnsureOutcome:
        return EnsureOutcome(status="exists")

    def guard_remote(self, path: Path) -> None:
        return

    def reachable(self) -> bool:
        return True

    def push(self, path: Path, *, message: str | None = None) -> None:
        return

    def web_url(self, path: Path) -> str | None:
        return None


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Snapshot and restore BACKENDS so tests don't leak registrations."""
    saved = dict(BACKENDS)
    BACKENDS.clear()
    yield
    BACKENDS.clear()
    BACKENDS.update(saved)


class TestRegisterBackend:
    def test_register_and_lookup(self) -> None:
        backend = _StubBackend()
        register_backend("stub", backend)
        assert backend_for("stub") is backend

    def test_lookup_is_case_insensitive(self) -> None:
        backend = _StubBackend()
        register_backend("Stub", backend)
        assert backend_for("STUB") is backend

    def test_duplicate_raises(self) -> None:
        register_backend("dup", _StubBackend())
        with pytest.raises(ValueError, match="already registered"):
            register_backend("dup", _StubBackend())

    def test_unknown_raises_keyerror_listing_known(self) -> None:
        register_backend("known", _StubBackend())
        with pytest.raises(KeyError, match="known"):
            backend_for("missing")
