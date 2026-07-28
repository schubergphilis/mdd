"""Forward / reverse converter dispatch for SharePoint sync."""

from __future__ import annotations

import importlib.metadata
from typing import TYPE_CHECKING

from mdd.converters import converter_for, reverse_for

if TYPE_CHECKING:
    from pathlib import Path


def converter_version(ext: str) -> str:  # noqa: ARG001
    """Return a version string for the forward converter registered for *ext*."""
    try:
        return importlib.metadata.version("docling")
    except importlib.metadata.PackageNotFoundError:
        pass
    return "unknown"


def do_convert(src: Path, dest: Path) -> str:
    """Run the forward converter for *src* and write Markdown to *dest*.

    Dispatches through :data:`mdd.converters.CONVERTERS`.

    Returns the converter name string (for the ``converter`` frontmatter field).
    Raises RuntimeError if no converter is registered for the extension.
    """
    conv = converter_for(src)
    if conv is None:
        raise RuntimeError(
            f"No converter registered for extension {src.suffix!r}. Cannot convert to Markdown."
        )
    conv.convert(src, dest=dest)
    return f"docling-{src.suffix.lstrip('.').lower()}"


def do_render(md_path: Path, dest: Path) -> None:
    """Render *md_path* to *dest* via the reverse converter for *dest*'s extension.

    Dispatches through :data:`mdd.converters.REVERSE_CONVERTERS`.
    Raises RuntimeError if no reverse converter is registered.
    """
    rev = reverse_for(dest.suffix)
    if rev is None:
        raise RuntimeError(
            f"No reverse converter registered for extension {dest.suffix!r}. "
            "Cannot render Markdown to office format."
        )
    rev.render(md_path, dest=dest)
