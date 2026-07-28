"""Local-only mirror backend (spec S44).

The backend used when a sync runs without ``--push``: it never resolves
a remote, so the orchestrator commits the mirror work-tree and stops.
This is today's ``push=False`` path expressed as a backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mdd.mirror.protocol import EnsureOutcome

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.mirror.protocol import MirrorTarget


class LocalOnlyBackend:
    """A backend with no remote: commit only, never push."""

    def resolve_remote(self, target: MirrorTarget) -> str | None:  # noqa: ARG002
        return None

    def ensure_remote(self, target: MirrorTarget) -> EnsureOutcome:  # noqa: ARG002
        return EnsureOutcome(status="exists")

    def guard_remote(self, path: Path) -> None:  # noqa: ARG002
        # Nothing to guard — there is no remote to push to.
        return

    def reachable(self) -> bool:
        return False

    def web_url(self, path: Path) -> str | None:  # noqa: ARG002
        # No remote, so there is no page to link a mirrored file to.
        return None

    def push(self, path: Path, *, message: str | None = None) -> None:  # noqa: ARG002
        # A local-only backend never pushes; the orchestrator only calls
        # push when a remote was resolved, so reaching here is a caller
        # bug rather than a runtime condition worth a soft skip.
        raise RuntimeError("LocalOnlyBackend has no remote to push to")
