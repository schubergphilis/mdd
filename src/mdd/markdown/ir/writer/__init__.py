"""IR → Markdown writer.

Entry point: ``render_markdown(doc: Document) -> str``.

Conventions:

* Standard CommonMark for headings, paragraphs, lists, blockquotes, code,
  tables, hr.
* ``Strikethrough`` → ``~~...~~``.
* ``Callout`` → ``:::callout-<kind>`` fenced div.
* ``ConfluenceMacro`` → ``:::confluence-macro {name=X ...}`` fenced div.
* ``ConfluenceLink`` / ``ConfluenceImage`` → synthetic-URI links via
  :mod:`.confluence_uris`.
* ``InlineMacro`` → ``{{confluence:name key="value" ...}}``.
* ``Emoticon`` → ``{{confluence:emoticon name="<name>"}}``.
* ``Placeholder`` → ``{{confluence:placeholder content="<content>"}}``.
* ``RawBlock(format="markdown")`` → verbatim.
* ``RawBlock(format="confluence-storage")`` → ``confluence-xml`` fence.
* ``RawBlock(format="html")`` → verbatim (CommonMark-compatible).
* ``Layout`` / ``LayoutSection`` / ``LayoutCell`` → fenced divs.
* Tables with merged cells → HTML table fallback.

Topic-grouped sub-modules: ``escape``, ``inlines``, ``table``, ``blocks``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from .blocks import render_block

if TYPE_CHECKING:
    from mdd.ir.document import Document

__all__ = ["render_markdown"]


def render_markdown(
    doc: Document,
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> str:
    """Render *doc* to a markdown string.

    ``mode`` controls whether ``Origin`` metadata is used:

    - ``"normalising"`` (default): ``Origin`` is ignored; canonical markdown is emitted.
    - ``"preserving"``: when a ``Text`` node or ``RawBlock`` / ``RawInline`` carries
      an ``Origin`` with ``raw_bytes``, the verbatim bytes are emitted instead of the
      canonical form. ``leading_ws`` / ``trailing_ws`` from ``Origin`` are emitted
      around structural nodes that carry them.
    """
    parts: list[str] = []
    for i, block in enumerate(doc.children):
        if i > 0:
            parts.append("\n\n")
        render_block(block, parts, indent="", mode=mode)
    parts.append("\n")
    return "".join(parts)
