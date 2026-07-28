"""Recursive block / inline walkers used by every normalisation pass.

These helpers are package-private: each pass imports them from
``._map``; nothing outside ``mdd.ir.normalize`` reaches in.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ..nodes import (
    Block,
    BlockQuote,
    BulletList,
    Callout,
    ConfluenceMacro,
    Heading,
    Inline,
    Layout,
    LayoutSection,
    OrderedList,
    Paragraph,
    Table,
    TableRow,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..document import Document


def map_blocks(blocks: list[Block], fn: Callable[[Block], Block]) -> list[Block]:
    """Apply *fn* to every block in *blocks*, recursing into nested blocks."""
    result: list[Block] = []
    for block in blocks:
        mapped = fn(block)
        result.append(mapped)
    return result


def _descend_block(block: Block, list_fn: Callable[[list[Block]], list[Block]]) -> Block:
    """Rebuild *block*'s nested block-list children via *list_fn*.

    The structural walk shared by ``map_block_children`` and ``filter_blocks``:
    both descend the same closed set of block containers and differ only in
    the per-list transform. Centralising the walk keeps the container shapes
    in one place — adding a new container kind touches one function, not two.
    """
    if isinstance(block, (BulletList, OrderedList)):
        new_items = [replace(item, children=list_fn(item.children)) for item in block.items]
        return replace(block, items=new_items)
    if isinstance(block, BlockQuote):
        return replace(block, children=list_fn(block.children))
    if isinstance(block, (Callout, ConfluenceMacro)):
        return replace(block, body=list_fn(block.body))
    if isinstance(block, Table):
        return replace(block, rows=_descend_table_rows(block.rows, list_fn))
    if isinstance(block, Layout):
        return replace(block, sections=_descend_layout_sections(block.sections, list_fn))
    return block


def _descend_table_rows(
    rows: list[TableRow], list_fn: Callable[[list[Block]], list[Block]]
) -> list[TableRow]:
    return [
        replace(
            row,
            cells=[replace(cell, children=list_fn(cell.children)) for cell in row.cells],
        )
        for row in rows
    ]


def _descend_layout_sections(
    sections: list[LayoutSection], list_fn: Callable[[list[Block]], list[Block]]
) -> list[LayoutSection]:
    return [
        replace(
            section,
            cells=[replace(cell, children=list_fn(cell.children)) for cell in section.cells],
        )
        for section in sections
    ]


def map_block_children(block: Block, fn: Callable[[Block], Block]) -> Block:
    """Recursively descend into block containers and apply *fn*."""
    return _descend_block(block, lambda blocks: map_blocks(blocks, fn))


def transform_blocks(doc: Document, fn: Callable[[Block], Block]) -> Document:
    """Apply *fn* to every block in the document tree, recursing into containers."""

    def recurse(block: Block) -> Block:
        descended = map_block_children(block, recurse)
        return fn(descended)

    return replace(doc, children=map_blocks(doc.children, recurse))


def transform_text_blocks(
    doc: Document,
    fn: Callable[[list[Inline]], list[Inline]],
    *,
    skip_identity_paragraphs: bool = False,
) -> Document:
    """Apply *fn* to ``.inlines`` of every ``Paragraph``/``Heading`` in the doc.

    The only blocks that carry inline content directly are ``Paragraph`` and
    ``Heading`` (per :class:`mdd.ir.nodes`). All other blocks pass through.
    ``replace`` is skipped when *fn* returns the original list unchanged so
    identity-sensitive callers don't see spurious node replacements.

    With ``skip_identity_paragraphs=True``, ``Paragraph`` nodes whose
    ``identity`` field is set are left alone — Confluence's positional
    anchors (``<p local-id="…">``) must round-trip byte-for-byte regardless
    of any inline transform applied around them.
    """

    _IDENTITY_KEYS: frozenset[str] = frozenset({"ac:local-id", "ac:macro-id", "local-id"})

    def transform(block: Block) -> Block:
        if (
            skip_identity_paragraphs
            and isinstance(block, Paragraph)
            and any(k in _IDENTITY_KEYS for k in block.attributes)
        ):
            return block
        if not isinstance(block, (Paragraph, Heading)):
            return block
        new_inlines = fn(block.inlines)
        return replace(block, inlines=new_inlines) if new_inlines != block.inlines else block

    return transform_blocks(doc, transform)


def filter_blocks(doc: Document, predicate: Callable[[Block], bool]) -> Document:
    """Remove top-level and nested blocks for which *predicate* returns False."""

    def filter_list(blocks: list[Block]) -> list[Block]:
        return [_descend_block(b, filter_list) for b in blocks if predicate(b)]

    return replace(doc, children=filter_list(doc.children))
