"""Mirror-backend seam for the sync engines.

`mdd`'s Confluence / SharePoint / Lucid sync engines all end a run the
same way: commit the mirror work-tree and (optionally) push it to a
remote, auto-creating the remote project on cold-start. The *where* and
*how* of that remote — URL derivation, project auto-create, the push
guard, and a reachability probe — is the only provider-specific part.

This package extracts that provider-specific part behind a
:class:`~mdd.mirror.protocol.MirrorBackend` seam, mirroring the
converter-registry pattern (a ``Protocol`` + a module-level ``dict`` +
an explicit ``register`` that raises on duplicates + a lookup helper).
The generic commit-and-push orchestration lives in
:mod:`mdd.mirror.orchestrator`; concrete backends live in
:mod:`mdd.mirror.local` and :mod:`mdd.mirror.git`; a distribution that
wraps this one adds its own forge-specific backend.
"""

from mdd.mirror.git import GenericGitBackend
from mdd.mirror.local import LocalOnlyBackend
from mdd.mirror.protocol import (
    EnsureOutcome,
    EnsureStatus,
    MirrorBackend,
    MirrorTarget,
)
from mdd.mirror.registry import (
    BACKENDS,
    backend_for,
    default_backend,
    default_backend_name,
    register_backend,
    set_default_backend,
)

# Built-in provider-agnostic backends. A wrapper distribution registers
# its own forge-specific backend from its CLI entry point.
register_backend("git", GenericGitBackend())
register_backend("local", LocalOnlyBackend())

__all__ = [
    "BACKENDS",
    "EnsureOutcome",
    "EnsureStatus",
    "GenericGitBackend",
    "LocalOnlyBackend",
    "MirrorBackend",
    "MirrorTarget",
    "backend_for",
    "default_backend",
    "default_backend_name",
    "register_backend",
    "set_default_backend",
]
