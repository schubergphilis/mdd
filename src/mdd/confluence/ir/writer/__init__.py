"""IR → Confluence storage XHTML.

Walks the IR and emits storage XHTML matching the shapes the reader
recognises.  Identity (``ac:macro-id`` / ``ac:local-id`` / ``local-id``)
is re-emitted on the corresponding output elements, so a round-trip on
unmodified content preserves macro IDs end-to-end.

``RawBlock`` / ``RawInline`` with format ``"confluence-storage"``,
``"xhtml"``, or ``"html"`` are passed through verbatim — CommonMark
raw-HTML blocks (e.g. ``<details>…</details>``) are valid storage XML.
Other ``RawBlock`` formats are wrapped in an HTML comment + ``<pre>``
(visible, surface-loss).

Spike fix 2: ``<ol start="1">`` is always emitted (not suppressed when
the default) so round-trips preserve the attribute verbatim.

Public surface: :func:`render_confluence_storage`. Topic-grouped
sub-modules: ``entities``, ``code``, ``links``, ``macros``, ``inlines``,
``table``, ``layout``, ``blocks``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from .blocks import render_block

if TYPE_CHECKING:
    from mdd.ir.document import Document

__all__ = ["render_confluence_storage"]


def render_confluence_storage(
    doc: Document,
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> str:
    """Render an IR ``Document`` to a Confluence storage XHTML string.

    ``mode`` controls how ``Origin`` metadata is used:

    - ``"normalising"`` (default): ``Origin`` is ignored; canonical XHTML is emitted.
    - ``"preserving"``: when a node carries an ``Origin``, its ``leading_ws`` /
      ``trailing_ws`` are emitted around the node, and ``entity_form`` is used to
      re-substitute the original HTML entity at each recorded codepoint offset in
      ``Text`` content instead of emitting the canonical Unicode form.
    """
    out: list[str] = []
    for i, block in enumerate(doc.children):
        if i > 0:
            # Honour the previous block's `trailing_ws` typed field when the
            # reader captured it; fall back to canonical "\n" when ``None``
            # (markdown-sourced blocks, never captured). An empty string is
            # a valid captured value ("no whitespace between blocks").
            # Honoured in either mode: the reader populates it from source
            # whitespace, and re-emitting it raises M1 even in normalising mode.
            prev_trailing_ws = getattr(doc.children[i - 1], "trailing_ws", None)
            out.append(prev_trailing_ws if isinstance(prev_trailing_ws, str) else "\n")
        render_block(block, out, mode=mode)
    return "".join(out)
