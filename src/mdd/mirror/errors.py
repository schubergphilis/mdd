"""Exceptions for the mirror seam."""

from __future__ import annotations


class MirrorError(Exception):
    """Base class for mirror-seam failures (commit / bootstrap / push)."""


class MirrorBootstrapError(MirrorError):
    """Raised when ``git init`` / ``git remote add`` fails for a mirror dir."""


class MirrorEnsureError(MirrorError):
    """Raised when the remote project could not be verified or created."""


class MirrorPushError(MirrorError):
    """Raised when a mirror push cannot proceed."""
