"""Callout-extraction pass: typed ``[!kind]`` block-quote prefixes."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from ..nodes import (
    Block,
    BlockQuote,
    Callout,
    Inline,
    Paragraph,
    Text,
)
from ._map import transform_blocks

if TYPE_CHECKING:
    from ..document import Document

_CALLOUT_KIND_RE = re.compile(r"^\[!(tip|note|warning|info|panel)\]\s*", re.IGNORECASE)


def _extract_callout_kind(blocks: list[Block]) -> tuple[str, list[Block]] | None:
    """If *blocks* starts with a ``Paragraph`` whose first inline is ``[!kind]``,
    return ``(kind, remaining_blocks)``; else return ``None``."""
    if not blocks:
        return None
    first = blocks[0]
    if not isinstance(first, Paragraph):
        return None
    if not first.inlines:
        return None
    first_inline = first.inlines[0]
    if not isinstance(first_inline, Text):
        return None
    m = _CALLOUT_KIND_RE.match(first_inline.content)
    if not m:
        return None
    kind = m.group(1).lower()
    rest_text = first_inline.content[m.end() :]
    remaining_inlines: list[Inline] = []
    if rest_text:
        remaining_inlines.append(Text(rest_text))
    remaining_inlines.extend(first.inlines[1:])
    body: list[Block] = []
    if remaining_inlines:
        body.append(replace(first, inlines=remaining_inlines))
    body.extend(blocks[1:])
    return kind, body


def attach_callout_kind(doc: Document) -> Document:
    """Map ``BlockQuote`` with ``[!kind]`` prefix into a typed ``Callout``."""

    def transform(block: Block) -> Block:
        if not isinstance(block, BlockQuote):
            return block
        extracted = _extract_callout_kind(block.children)
        if extracted is None:
            return block
        kind, body = extracted
        valid_kinds = {"tip", "note", "warning", "info", "panel"}
        if kind not in valid_kinds:
            return block
        return Callout(
            kind=kind,  # pyright: ignore[reportArgumentType]
            body=body,
            node_id=block.node_id,
            attributes=block.attributes,
        )

    return transform_blocks(doc, transform)
