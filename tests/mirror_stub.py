"""A stub :class:`~mdd.mirror.protocol.MirrorBackend` for tests.

Tests that exercise the push path need *a* backend, but not a particular
one — and hard-coding a forge-specific backend's URLs makes those tests
fail in any distribution that ships a different one (spec S44).
Registering a stub with a known remote keeps the assertions about the
sync engine rather than about which forge happens to be wired.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from mdd.mirror.protocol import EnsureOutcome
from mdd.mirror.registry import BACKENDS, default_backend_name, set_default_backend

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from mdd.mirror.protocol import MirrorTarget

STUB_HOST = "git.test.example"
STUB_GROUP = "mirrors"


class StubBackend:
    """Resolves every target to ``https://git.test.example/mirrors/<key>.git``."""

    def __init__(
        self,
        *,
        on_push: Callable[[Path, str | None], None] | None = None,
        web_url: str | None = None,
    ) -> None:
        self.pushes: list[tuple[Path, str | None]] = []
        self.ensured: list[MirrorTarget] = []
        self.guarded: list[Path] = []
        self.web_urls_asked: list[Path] = []
        self._on_push = on_push
        self._web_url = web_url

    def resolve_remote(self, target: MirrorTarget) -> str:
        return f"https://{STUB_HOST}/{STUB_GROUP}/{target.key}.git"

    def ensure_remote(self, target: MirrorTarget) -> EnsureOutcome:
        self.ensured.append(target)
        return EnsureOutcome(status="exists", remote_url=self.resolve_remote(target))

    def guard_remote(self, path: Path) -> None:
        self.guarded.append(path)

    def reachable(self) -> bool:
        return True

    def web_url(self, path: Path) -> str | None:
        # Defaults to None — the no-footer case — so tests that do not care
        # about the footer are unaffected by this method existing.
        self.web_urls_asked.append(path)
        return self._web_url

    def push(self, path: Path, *, message: str | None = None) -> None:
        self.pushes.append((path, message))
        if self._on_push is not None:
            self._on_push(path, message)


@contextmanager
def stub_backend(
    *,
    name: str = "stub-test",
    on_push: Callable[[Path, str | None], None] | None = None,
    web_url: str | None = None,
) -> Generator[StubBackend]:
    """Register a :class:`StubBackend` as the default for the duration.

    Restores the previous default and de-registers the stub on exit, so
    tests stay independent of each other's wiring.
    """
    backend = StubBackend(on_push=on_push, web_url=web_url)
    previous_default = default_backend_name()
    previous_entry = BACKENDS.get(name)
    BACKENDS[name] = backend
    set_default_backend(name)
    try:
        yield backend
    finally:
        if previous_entry is None:
            del BACKENDS[name]
        else:
            BACKENDS[name] = previous_entry
        if previous_default is not None:
            set_default_backend(previous_default)
