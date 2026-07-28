"""Markdown ↔ IR converters.

Public surface per spec S30, spec S31:

    parse_markdown(md, *, ctx=None, mode="normalising") -> Document
    render_markdown(doc, *, mode="normalising") -> str

``mode`` defaults to ``"normalising"``. In normalising mode the
``NORMALISING_PIPELINE`` is applied to the parsed ``Document`` before it is
returned. In preserving mode, ``Origin`` metadata is captured and the
normalisation pipeline is skipped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from mdd.ir.normalize import normalise

from .reader import parse_markdown as _parse_markdown_raw
from .writer import render_markdown as _render_markdown_raw

if TYPE_CHECKING:
    from mdd.ir.document import Document
    from mdd.ir.fallback import IRContext


def parse_markdown(
    md: str,
    *,
    ctx: IRContext | None = None,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> Document:
    """Parse *md* into a ``Document``.

    In ``"normalising"`` mode (the default), the ``NORMALISING_PIPELINE`` is
    applied to the parsed document before returning. In ``"preserving"`` mode,
    the pipeline is skipped and ``Origin`` metadata is attached to text leaves
    for byte-perfect round-trips.
    """
    doc = _parse_markdown_raw(md, ctx=ctx, mode=mode)
    if mode == "normalising":
        doc = normalise(doc)
    return doc


def render_markdown(
    doc: Document,
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> str:
    """Render *doc* to a markdown string.

    In ``"normalising"`` mode (the default), ``Origin`` metadata is ignored
    and canonical markdown is emitted. In ``"preserving"`` mode, ``Origin``
    metadata is used to emit the original bytes.
    """
    return _render_markdown_raw(doc, mode=mode)


__all__ = ["parse_markdown", "render_markdown"]
