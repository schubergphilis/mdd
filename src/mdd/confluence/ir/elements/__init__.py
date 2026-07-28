"""Element handlers for paragraphs, headings, lists, tables, code blocks, etc.

Each handler receives an lxml element and returns one or more IR ``Block``
nodes. Public surface:

- ``is_block_tag(tag)`` — block-vs-inline dispatch predicate.
- ``read_blocks_from_container(parent, ctx)`` — read a container's
  children into a list of IR ``Block`` nodes, wrapping bare inline
  content into synthetic ``Paragraph``s.

Topic-grouped sub-modules: ``block``, ``listing``, ``table``, ``inline``,
plus a private ``_namespaces`` module holding shared XML namespace
constants.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from mdd.ir.nodes import Block, Inline, Paragraph, Text

from ..images import read_ac_image
from ..links import read_ac_link
from ._namespaces import (
    AC,
    AC_IMAGE,
    AC_LINK,
    AC_STRUCTURED_MACRO,
    HEADING_TAGS,
    LAYOUT_TAGS,
    RI,
)
from .block import read_block
from .inline import read_inline, read_inline_children

if TYPE_CHECKING:
    from collections.abc import Callable

    from mdd.ir.fallback import IRContext

__all__ = ["is_block_tag", "read_blocks_from_container"]


def is_block_tag(tag: str) -> bool:
    """Return True when ``tag`` denotes a block-level element."""
    if tag in HEADING_TAGS:
        return True
    if tag in {"p", "ul", "ol", "blockquote", "hr", "pre", "table", "div"}:
        return True
    if tag in LAYOUT_TAGS:
        return True
    if tag == AC_STRUCTURED_MACRO:
        return True
    if tag in (AC_LINK, AC_IMAGE):
        return False
    return bool(tag.startswith((f"{{{AC}}}", f"{{{RI}}}")))


def _read_block_level_inline_wrapper(
    child: Any, tag: str, ctx: IRContext | None
) -> Paragraph | None:
    """Wrap a top-of-container ``<ac:link>`` or ``<ac:image>`` (no ``<p>``
    parent) in a synthetic ``Paragraph``. Returns ``None`` for any other tag.
    Setting ``block_level=True`` on the inline lets the writer emit it bare
    on the round-trip.
    """
    if tag == AC_LINK:

        def _read_inline_kids(n: Any) -> list[Inline]:
            return read_inline_children(n, ctx)

        return Paragraph(inlines=[read_ac_link(child, _read_inline_kids, block_level=True)])
    if tag == AC_IMAGE:
        img = read_ac_image(child)
        return Paragraph(inlines=[replace(img, block_level=True)])
    return None


def _capture_trailing_ws(blocks: list[Block], added_block: Block, tail_text: str) -> None:
    """When the most recent emission supports the ``trailing_ws`` field,
    replace it with a copy carrying the leading-whitespace prefix of the
    XML node's ``tail`` text. The writer consults this to round-trip the
    original inter-block whitespace.
    """
    if not hasattr(added_block, "trailing_ws"):
        return
    ws_len = len(tail_text) - len(tail_text.lstrip())
    ws_prefix = tail_text[:ws_len]
    blocks[-1] = replace(added_block, trailing_ws=ws_prefix)  # pyright: ignore[reportCallIssue]


def _emit_child(
    child: Any,
    tag: str,
    ctx: IRContext | None,
    blocks: list[Block],
    inline_buffer: list[Inline],
    flush_inline: Callable[[], None],
) -> Block | None:
    """Classify one XML child and route it to either a block emission or
    the running inline buffer. Returns the last block emitted (so the
    caller can attach trailing-whitespace metadata), or ``None`` when the
    child contributed only inlines.
    """
    if is_block_tag(tag):
        flush_inline()
        added = list(read_block(child, ctx))
        blocks.extend(added)
        return added[-1] if added else None
    block_wrapper = _read_block_level_inline_wrapper(child, tag, ctx)
    if block_wrapper is not None:
        flush_inline()
        blocks.append(block_wrapper)
        return block_wrapper
    inline_buffer.extend(read_inline(child, ctx))
    return None


def read_blocks_from_container(parent: Any, ctx: IRContext | None = None) -> list[Block]:
    """Read block-level children of ``parent`` into IR ``Block`` nodes.

    Inline content directly under ``parent`` (text nodes between block
    elements, or inline elements like ``<a>`` without an enclosing ``<p>``)
    gets wrapped in synthetic ``Paragraph`` nodes so the document tree is
    uniformly block-shaped.
    """
    blocks: list[Block] = []
    inline_buffer: list[Inline] = []

    def flush_inline() -> None:
        if not inline_buffer:
            return
        if any(not isinstance(t, Text) or t.content.strip() for t in inline_buffer):
            blocks.append(Paragraph(inlines=list(inline_buffer)))
        inline_buffer.clear()

    if parent.text:
        inline_buffer.append(Text(parent.text))

    for child in parent:
        tag = child.tag if isinstance(child.tag, str) else ""
        added_block = _emit_child(child, tag, ctx, blocks, inline_buffer, flush_inline)
        if added_block is not None:
            # ``trailing_ws=""`` is meaningful ("no whitespace between blocks")
            # and distinct from the ``None`` default ("not captured, writer
            # falls back to ``\n``"). Skip blocks that do not support the
            # field (e.g. RawBlock).
            _capture_trailing_ws(blocks, added_block, child.tail or "")
        if child.tail:
            inline_buffer.append(Text(child.tail))

    flush_inline()
    return blocks
