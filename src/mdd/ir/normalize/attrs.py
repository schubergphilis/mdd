"""Attribute normalisation passes: dedupe default values, sort keys."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from ..nodes import (
    Block,
    Table,
    TableCell,
    TableRow,
)
from ._map import transform_blocks

if TYPE_CHECKING:
    from ..document import Document

# Writer defaults for attributes that should be omitted when they equal the default.
_ATTR_DEFAULTS: dict[str, str] = {
    "colspan": "1",
    "rowspan": "1",
}


def _dedupe_dict(attributes: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in attributes.items() if _ATTR_DEFAULTS.get(k) != v}


def _dedupe_table_cells(block: Block) -> Block:
    """Apply _dedupe_dict to every TableCell.attributes inside a Table block."""
    if not isinstance(block, Table):
        return block
    new_rows: list[TableRow] = []
    for row in block.rows:
        new_cells: list[TableCell] = []
        for cell in row.cells:
            new_attributes = _dedupe_dict(cell.attributes)
            new_cells.append(
                replace(cell, attributes=new_attributes)
                if new_attributes != cell.attributes
                else cell
            )
        new_rows.append(replace(row, cells=new_cells) if new_cells != row.cells else row)
    return replace(block, rows=new_rows) if new_rows != block.rows else block


def dedupe_attrs(doc: Document) -> Document:
    """Remove ``attributes`` keys whose values equal writer defaults (e.g. ``colspan=1``)."""

    def transform(block: Block) -> Block:
        # Also clean cell-level attributes inside tables.
        block = _dedupe_table_cells(block)
        raw_attributes = getattr(block, "attributes", None)
        if not isinstance(raw_attributes, dict):
            return block
        current_attributes = cast("dict[str, str]", raw_attributes)
        new_attributes = _dedupe_dict(current_attributes)
        if new_attributes == current_attributes:
            return block
        return replace(block, attributes=new_attributes)  # pyright: ignore[reportCallIssue]

    return transform_blocks(doc, transform)


def _attributes_are_sorted(attributes: dict[str, str]) -> bool:
    keys = list(attributes.keys())
    return keys == sorted(keys)


def _has_storage_prefixed_keys(attributes: dict[str, str]) -> bool:
    """Return True if the dict looks like it came from Confluence storage.

    Storage-sourced dicts (from ``all_attrs_ordered()``) carry ``ac:``- or
    ``ri:``-prefixed keys, or Confluence-specific bare keys like ``local-id``.
    These dicts are already in source-document order; sorting them would
    reorder identity attributes and drop M1 below the round-trip threshold.
    """
    _BARE_STORAGE_KEYS: frozenset[str] = frozenset({"local-id"})
    return any(k.startswith(("ac:", "ri:")) or k in _BARE_STORAGE_KEYS for k in attributes)


def _sort_table_cells(block: Block) -> Block:
    """Apply sorted() to every TableCell.attributes inside a Table block."""
    if not isinstance(block, Table):
        return block
    changed = False
    new_rows: list[TableRow] = []
    for row in block.rows:
        new_cells: list[TableCell] = []
        row_changed = False
        for cell in row.cells:
            if not _attributes_are_sorted(cell.attributes) and not _has_storage_prefixed_keys(
                cell.attributes
            ):
                sorted_cell_attributes = dict(sorted(cell.attributes.items()))
                new_cells.append(replace(cell, attributes=sorted_cell_attributes))
                row_changed = True
            else:
                new_cells.append(cell)
        if row_changed:
            new_rows.append(replace(row, cells=new_cells))
            changed = True
        else:
            new_rows.append(row)
    return replace(block, rows=new_rows) if changed else block


def sort_attrs(doc: Document) -> Document:
    """Sort ``attributes`` dicts by key for deterministic output.

    Dicts that contain ``ac:``- or ``ri:``-prefixed keys are skipped: those
    came from Confluence storage via ``all_attrs_ordered()`` and are already
    in source-document order.  Sorting them would reorder identity attributes
    (``ac:local-id``, ``ac:macro-id``, …) and drop M1 below the round-trip
    threshold.
    """

    def transform(block: Block) -> Block:
        # Also sort cell-level attributes inside tables.
        block = _sort_table_cells(block)
        raw_attributes = getattr(block, "attributes", None)
        if not isinstance(raw_attributes, dict):
            return block
        current_attributes = cast("dict[str, str]", raw_attributes)
        if _attributes_are_sorted(current_attributes):
            return block
        if _has_storage_prefixed_keys(current_attributes):
            return block
        sorted_attributes = dict(sorted(current_attributes.items()))
        return replace(block, attributes=sorted_attributes)  # pyright: ignore[reportCallIssue]

    return transform_blocks(doc, transform)
