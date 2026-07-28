"""List-related normalisation passes: tighten lists, default ordered start."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ..nodes import (
    Block,
    BulletList,
    ListItem,
    OrderedList,
    Paragraph,
)
from ._map import transform_blocks

if TYPE_CHECKING:
    from ..document import Document


def _item_is_single_paragraph(item: ListItem) -> bool:
    return len(item.children) == 1 and isinstance(item.children[0], Paragraph)


def tighten_lists(doc: Document) -> Document:
    """Set ``tight=True`` when every ``ListItem`` has exactly one ``Paragraph`` child."""

    def transform(block: Block) -> Block:
        if isinstance(block, BulletList):
            if block.items and all(_item_is_single_paragraph(i) for i in block.items):
                return replace(block, tight=True)
            return block
        if isinstance(block, OrderedList):
            if block.items and all(_item_is_single_paragraph(i) for i in block.items):
                return replace(block, tight=True)
            return block
        return block

    return transform_blocks(doc, transform)


def default_ordered_start(doc: Document) -> Document:
    """Drop ``start=1`` on ``OrderedList`` (the writer default). Skipped in preserving mode."""

    def transform(block: Block) -> Block:
        if isinstance(block, OrderedList) and block.start == 1:
            return replace(block, start=1)  # already default — no field change needed
        return block

    # The pass itself is a no-op when start == 1 because start=1 IS the default.
    # The semantic purpose is to make the "canonical" form explicit; the writer
    # omits start=1 when rendering markdown. In preserving mode this pass is
    # skipped entirely by the caller. No transformation required here.
    return transform_blocks(doc, transform)
