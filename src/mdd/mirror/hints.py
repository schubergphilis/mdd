"""Human-facing hints derived from the mirror seam.

The CLI tells a user which repository to clone when it cannot work out which
mirror clone they meant. That URL is deployment knowledge, so it comes from the
registered backend rather than from a literal in the command module — the same
reason the Confluence footer asks the backend for a browse URL.
"""

from __future__ import annotations

from mdd.mirror.protocol import MirrorTarget
from mdd.mirror.registry import default_backend


def clone_hint(kind: str, key: str) -> str:
    """Return an indented ``git clone …`` line for the mirror of *key*.

    Falls back to prose when no backend is wired or the backend cannot derive a
    remote for the target (a local-only or plain-git deployment), so the caller
    can always print the result.
    """
    try:
        remote = default_backend().resolve_remote(MirrorTarget(kind=kind, key=key))
    except RuntimeError:
        remote = None
    if remote is None:
        return f"  (no {kind} mirror remote is configured for {key})"
    return f"  git clone {remote} && cd {key}"
