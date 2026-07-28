"""Confluence storage XHTML ↔ IR converters.

Public API (spec S29, spec S31):

- ``parse_confluence_storage(storage, *, ctx, page_title, mode)`` → ``Document``
- ``render_confluence_storage(doc, *, mode)`` → ``str``

``mode`` defaults to ``"normalising"``. In normalising mode the pipeline from
``mdd.ir.normalize`` is applied to the parsed ``Document`` before it is
returned. In preserving mode, ``Origin`` metadata is captured and the
normalisation pipeline is skipped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from mdd.ir.normalize import normalise

from .attachment_refs import AttachmentRef, collect_attachment_refs
from .reader import parse_confluence_storage as _parse_confluence_storage_raw
from .writer import render_confluence_storage as _render_confluence_storage_raw

if TYPE_CHECKING:
    from mdd.ir.document import Document
    from mdd.ir.fallback import IRContext


def parse_confluence_storage(
    storage: str,
    *,
    ctx: IRContext | None = None,
    page_title: str | None = None,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> Document:
    """Parse a Confluence storage XHTML fragment to an IR ``Document``.

    In ``"normalising"`` mode (the default), the ``NORMALISING_PIPELINE`` is
    applied to the parsed document before returning so the caller gets a
    clean, diff-friendly representation. In ``"preserving"`` mode, the
    pipeline is skipped and ``Origin`` metadata is attached to nodes for
    byte-perfect round-trips.
    """
    doc = _parse_confluence_storage_raw(storage, ctx=ctx, page_title=page_title, mode=mode)
    if mode == "normalising":
        doc = normalise(doc)
    return doc


def render_confluence_storage(
    doc: Document,
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> str:
    """Render an IR ``Document`` to a Confluence storage XHTML string.

    In ``"normalising"`` mode (the default), ``Origin`` metadata is ignored
    and canonical XHTML is emitted. In ``"preserving"`` mode, ``Origin``
    metadata is used to re-emit the original bytes and entities.
    """
    return _render_confluence_storage_raw(doc, mode=mode)


__all__ = [
    "AttachmentRef",
    "collect_attachment_refs",
    "parse_confluence_storage",
    "render_confluence_storage",
]
