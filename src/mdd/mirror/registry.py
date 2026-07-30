"""Backend registry for the mirror seam.

Mirrors :mod:`mdd.converters.registry`: a module-level ``dict`` keyed by
a normalized name, an explicit :func:`register_backend` that raises on a
duplicate key, and a :func:`backend_for` lookup helper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mdd.mirror.protocol import MirrorBackend

# Keyed by lowercased backend name, e.g. "gitlab", "git", "local".
BACKENDS: dict[str, MirrorBackend] = {}

# The backend name the CLI entry point (build_dispatcher) wired as the
# default. None until set, so a stray resolution before wiring is a loud
# error rather than a silent wrong-backend. Kept out of source as a fixed
# literal so the OSS core has no built-in house default.
_default_name: str | None = None


def _normalize(name: str) -> str:
    return name.strip().lower()


def register_backend(name: str, backend: MirrorBackend) -> None:
    """Register *backend* under *name*.

    Raises ValueError if *name* is already registered.
    """
    key = _normalize(name)
    if key in BACKENDS:
        raise ValueError(
            f"Backend {key!r} is already registered to "
            f"{type(BACKENDS[key]).__name__!r}; "
            f"cannot register {type(backend).__name__!r}"
        )
    BACKENDS[key] = backend


def backend_for(name: str) -> MirrorBackend:
    """Return the backend registered under *name*.

    Raises KeyError with the set of known names if *name* is unknown.
    """
    key = _normalize(name)
    try:
        return BACKENDS[key]
    except KeyError as exc:
        known = ", ".join(sorted(BACKENDS)) or "(none)"
        raise KeyError(
            f"No mirror backend registered for {name!r}. Known backends: {known}"
        ) from exc


def set_default_backend(name: str) -> None:
    """Record *name* as the default backend for the sync engines.

    Called once by :func:`mdd.cli.build_dispatcher` so a wrapper can pick
    ``"git"`` / ``"github"`` / ``"gitlab"`` without editing the core.
    """
    global _default_name
    _default_name = _normalize(name)


def default_backend_name() -> str | None:
    """Return the name wired as the default, or ``None`` if none is set yet.

    Exposed so callers that need to save and restore the wiring (tests,
    and a wrapper that composes more than one dispatcher) don't have to
    reach for the module global.
    """
    return _default_name


def default_backend() -> MirrorBackend:
    """Return the backend wired as the default by ``build_dispatcher``.

    Raises RuntimeError if no default has been set yet.
    """
    if _default_name is None:
        raise RuntimeError(
            "No default mirror backend set; call set_default_backend() "
            "(mdd.cli.build_dispatcher does this) first."
        )
    return backend_for(_default_name)
