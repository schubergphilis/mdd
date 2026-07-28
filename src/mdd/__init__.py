"""The mdd package: Markdown and Quarto document tooling."""

from __future__ import annotations

import importlib.metadata


def _version() -> str:
    """Return the installed mdd distribution version.

    Reads the version from the installed distribution metadata
    (setuptools-scm derives it from git tags at build/install time).
    Falls back to ``"0.0.0"`` when the package is not installed as a
    distribution (e.g. run straight from a source tree).
    """
    try:
        return importlib.metadata.version("mdd")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


__version__ = _version()


def greet(name: str) -> str:
    """Return a greeting for the given name."""
    if not name:
        raise ValueError("name must not be empty")
    return f"Hello, {name}!"
