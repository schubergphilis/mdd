"""MirrorBackend protocol + result dataclasses (spec S44).

Mirrors the converter-registry pattern (spec S15): a ``Protocol`` plus
small frozen dataclasses describing the seam's inputs and outputs.
Concrete backends live in sibling modules (:mod:`mdd.mirror.local`,
:mod:`mdd.mirror.git`) and provider packages (:mod:`mdd.gitlab.backend`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class MirrorTarget:
    """Identifies one mirror destination for a sync engine.

    *kind* is the sync engine name (``"confluence"``, ``"sharepoint"``,
    ``"lucid"``); *key* is the engine-specific identity (space key, site
    repo name, Lucid folder slug). A backend maps a target to a concrete
    remote (URL + project path).
    """

    kind: str
    key: str


EnsureStatus = Literal["created", "exists", "unreachable"]


@dataclass(frozen=True)
class EnsureOutcome:
    """Outcome of :meth:`MirrorBackend.ensure_remote`.

    ``status`` is one of:

    - ``"created"`` — the remote project did not exist and was created;
    - ``"exists"`` — the remote project already existed;
    - ``"unreachable"`` — the remote couldn't be reached (e.g. VPN down)
      or the provider CLI isn't installed. Callers should let the
      subsequent push surface the underlying problem rather than emit a
      second failure.

    ``remote_url`` is the resolved clone URL when known; ``reason``
    carries a human-readable explanation for the ``"unreachable"`` case.
    """

    status: EnsureStatus
    remote_url: str | None = None
    reason: str | None = None


class MirrorBackend(Protocol):
    """Provider seam for the sync engines' git-mirror push step (spec S44).

    Extracts the provider-specific operations out of the otherwise
    generic commit-and-push orchestration:

    - :meth:`resolve_remote` — derive the clone URL for a target (used
      for the cold-start bootstrap); ``None`` when the backend has no
      remote (local-only).
    - :meth:`ensure_remote` — verify-or-create the remote project for a
      target.
    - :meth:`guard_remote` — raise if pushing the work-tree at *path* is
      not permitted (host allow-list + data-protection gate).
    - :meth:`reachable` — a cheap probe (e.g. VPN) reporting whether a
      push is worth attempting.
    - :meth:`push` — perform the actual push. Generic git for most
      backends, but a seam method so a provider (GitLab) can route it
      through its own guarded push implementation.
    """

    def resolve_remote(self, target: MirrorTarget) -> str | None:
        """Return the clone URL for *target*, or ``None`` if this backend has no remote."""
        ...

    def ensure_remote(self, target: MirrorTarget) -> EnsureOutcome:
        """Verify-or-create the remote project for *target*."""
        ...

    def guard_remote(self, path: Path) -> None:
        """Raise if pushing the work-tree at *path* is not permitted."""
        ...

    def reachable(self) -> bool:
        """Return True if the remote is reachable (best-effort)."""
        ...

    def push(self, path: Path, *, message: str | None = None) -> None:
        """Commit any dirty changes with *message* and push the work-tree at *path*."""
        ...
