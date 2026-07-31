"""Identity and provenance helpers.

Two responsibilities:

1. `IdAllocator` / `assign_ids` — hand out monotonic `b00001`
   labels during parse, walking depth-first.
2. `reattach` — graft `identity` and `node_id` from a previously
   cached IR onto a freshly-parsed IR wherever the structural
   shapes match. Unchanged content keeps its identity across a
   round-trip; edits surface as identity loss in the diff.
"""

from __future__ import annotations

from dataclasses import is_dataclass, replace
from typing import TYPE_CHECKING, Any, cast

from .nodes import (
    Block,
    BlockQuote,
    BulletList,
    Callout,
    Code,
    CodeBlock,
    ConfluenceLink,
    ConfluenceMacro,
    Emph,
    Heading,
    HorizontalRule,
    Inline,
    Layout,
    LayoutCell,
    LayoutSection,
    LineBreak,
    Link,
    ListItem,
    OrderedList,
    Paragraph,
    RawBlock,
    SoftBreak,
    Strikethrough,
    Strong,
    Table,
    TableCell,
    TableRow,
    Text,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .document import Document


class IdAllocator:
    """Hands out block-level `b00001`-style identifiers."""

    def __init__(self, start: int = 1) -> None:
        self._next = start

    def next(self) -> str:
        n = self._next
        self._next += 1
        return f"b{n:05d}"

    @property
    def counter(self) -> int:
        return self._next - 1


def assign_ids(doc: Document) -> Document:
    """Walk depth-first and assign `node_id` to every block missing one."""
    alloc = IdAllocator()
    new_children = [_assign_block(b, alloc) for b in doc.children]
    return replace(doc, children=new_children, node_id_counter=alloc.counter)


def _assign_block(block: Block, alloc: IdAllocator) -> Block:  # noqa: PLR0911
    nid = block.node_id or alloc.next()
    if isinstance(block, (Paragraph, Heading, HorizontalRule, CodeBlock, RawBlock)):
        return replace(block, node_id=nid)
    if isinstance(block, BulletList):
        items = [_assign_list_item(it, alloc) for it in block.items]
        return replace(block, node_id=nid, items=items)
    if isinstance(block, OrderedList):
        items = [_assign_list_item(it, alloc) for it in block.items]
        return replace(block, node_id=nid, items=items)
    if isinstance(block, BlockQuote):
        children = [_assign_block(c, alloc) for c in block.children]
        return replace(block, node_id=nid, children=children)
    if isinstance(block, Callout):
        body = [_assign_block(c, alloc) for c in block.body]
        return replace(block, node_id=nid, body=body)
    if isinstance(block, ConfluenceMacro):
        body = [_assign_block(c, alloc) for c in block.body]
        return replace(block, node_id=nid, body=body)
    if isinstance(block, Table):
        rows = [_assign_table_row(r, alloc) for r in block.rows]
        return replace(block, node_id=nid, rows=rows)
    # By exhaustion this branch handles Layout — the union is closed.
    sections = [_assign_layout_section(s, alloc) for s in block.sections]
    return replace(block, node_id=nid, sections=sections)


def _assign_list_item(item: ListItem, alloc: IdAllocator) -> ListItem:
    nid = item.node_id or alloc.next()
    children = [_assign_block(c, alloc) for c in item.children]
    return replace(item, node_id=nid, children=children)


def _assign_table_row(row: TableRow, alloc: IdAllocator) -> TableRow:
    cells = [_assign_table_cell(c, alloc) for c in row.cells]
    return replace(row, cells=cells)


def _assign_table_cell(cell: TableCell, alloc: IdAllocator) -> TableCell:
    children = [_assign_block(c, alloc) for c in cell.children]
    return replace(cell, children=children)


def _assign_layout_section(section: LayoutSection, alloc: IdAllocator) -> LayoutSection:
    cells = [_assign_layout_cell(c, alloc) for c in section.cells]
    return replace(section, cells=cells)


def _assign_layout_cell(cell: LayoutCell, alloc: IdAllocator) -> LayoutCell:
    children = [_assign_block(c, alloc) for c in cell.children]
    return replace(cell, children=children)


# ---------------------------------------------------------------------------
# Reattach
# ---------------------------------------------------------------------------


def reattach(fresh: Document, cached: Document) -> Document:
    """Copy `identity` and `node_id` from `cached` onto `fresh` where shapes match."""
    new_children = _reattach_blocks(fresh.children, cached.children)
    return replace(
        fresh,
        children=new_children,
        page_title=fresh.page_title or cached.page_title,
        node_id_counter=max(fresh.node_id_counter, cached.node_id_counter),
    )


def _reattach_blocks(fresh: list[Block], cached: list[Block]) -> list[Block]:
    out: list[Block] = []
    for i, fnode in enumerate(fresh):
        if i < len(cached) and type(fnode) is type(cached[i]):
            out.append(_reattach_block(fnode, cached[i]))
        else:
            out.append(fnode)
    return out


def _merge_attributes_onto(
    fresh: dict[str, str],
    cached: dict[str, str],
    *,
    skip: frozenset[str] = frozenset(),
) -> dict[str, str] | None:
    """Merge cached ``attributes`` keys absent from fresh.

    Source-order attrs (e.g. ``ac:local-id``, ``ac:macro-id``, passthrough
    HTML attrs) that aren't already in fresh are grafted from cached so the
    storage writer can re-emit them on the round-trip. Fresh wins where it
    has a value. Returns the merged dict, or ``None`` if nothing changed.
    """
    merged: dict[str, str] = dict(fresh)
    for k, v in cached.items():
        if k not in skip and k not in merged:
            merged[k] = v
    return merged if merged != fresh else None


def _graft_list_typed_fields(
    fresh: BulletList | OrderedList,
    cached: BulletList | OrderedList,
    updates: dict[str, Any],
) -> None:
    if cached.compact and not fresh.compact:
        updates["compact"] = True
    if (
        isinstance(fresh, OrderedList)
        and isinstance(cached, OrderedList)
        and cached.omit_start
        and not fresh.omit_start
    ):
        updates["omit_start"] = True


def _graft_body_ws(fresh: Any, cached: Any, updates: dict[str, Any]) -> None:
    if not fresh.body_leading_ws and cached.body_leading_ws:
        updates["body_leading_ws"] = cached.body_leading_ws
    if not fresh.body_trailing_ws and cached.body_trailing_ws:
        updates["body_trailing_ws"] = cached.body_trailing_ws


def _graft_common_node_metadata(fresh: Block, cached: Block, updates: dict[str, Any]) -> None:
    """Graft `origin` and `trailing_ws` from cached onto fresh.

    Markdown leg drops both. ``trailing_ws=""`` is a meaningful captured value
    ("no whitespace between blocks") distinct from the ``None`` default.
    """
    c_origin = getattr(cached, "origin", None)
    if c_origin is not None and hasattr(fresh, "origin"):
        updates["origin"] = c_origin
    c_trailing_ws = getattr(cached, "trailing_ws", None)
    if (
        c_trailing_ws is not None
        and hasattr(fresh, "trailing_ws")
        and getattr(fresh, "trailing_ws", None) is None
    ):
        updates["trailing_ws"] = c_trailing_ws


def _graft_code_block_typed_fields(fresh: Block, cached: Block, updates: dict[str, Any]) -> None:
    if (
        isinstance(fresh, CodeBlock)
        and isinstance(cached, CodeBlock)
        and cached.no_wrapper
        and not fresh.no_wrapper
    ):
        updates["no_wrapper"] = True


def _graft_attributes_block(fresh: Block, cached: Block, updates: dict[str, Any]) -> None:
    """Graft cached source-order attributes onto fresh.

    Restores passthrough attrs (e.g. ``ac:name``, ``ac:schema-version``,
    ``data-layout``, ``ac:local-id``) that the markdown leg drops but the
    storage writer needs.
    """
    c_attributes = getattr(cached, "attributes", None)
    f_attributes = getattr(fresh, "attributes", None)
    if not (isinstance(c_attributes, dict) and isinstance(f_attributes, dict) and c_attributes):
        return
    merged = _merge_attributes_onto(
        cast("dict[str, str]", f_attributes), cast("dict[str, str]", c_attributes)
    )
    if merged is not None:
        updates["attributes"] = merged


def _graft_list_block(
    fresh: BulletList | OrderedList,
    cached: BulletList | OrderedList,
    updates: dict[str, Any],
) -> None:
    updates["items"] = [
        _reattach_list_item(f, cached.items[i]) if i < len(cached.items) else f
        for i, f in enumerate(fresh.items)
    ]
    _graft_list_typed_fields(fresh, cached, updates)


def _graft_blockquote_block(fresh: BlockQuote, cached: BlockQuote, updates: dict[str, Any]) -> None:
    updates["children"] = _reattach_blocks(fresh.children, cached.children)


def _graft_callout_block(fresh: Callout, cached: Callout, updates: dict[str, Any]) -> None:
    """Reattach a Callout pair: body, params, title, body whitespace.

    The markdown round-trip strips params with complex attribute values
    (JSON-style entity runs in fixtures like 1114411 emit
    ``{&quot;…&quot;}`` strings that the fenced-div info parser can't
    round-trip). Restore from cached when the fresh side dropped them
    entirely — keep the fresh side when it's non-empty so a genuine edit
    survives.
    """
    updates["body"] = _reattach_blocks(fresh.body, cached.body)
    if not fresh.params and cached.params:
        updates["params"] = dict(cached.params)
    if fresh.title is None and cached.title is not None:
        updates["title"] = cached.title
    _graft_body_ws(fresh, cached, updates)


def _graft_macro_block(
    fresh: ConfluenceMacro, cached: ConfluenceMacro, updates: dict[str, Any]
) -> None:
    """Reattach a ConfluenceMacro pair.

    Always graft cached metadata when both sides are ConfluenceMacro at the
    same position. The markdown leg can drop the macro name (fixture
    1114411) or wrap an empty body as ``rich_body=True`` (fixtures 1081534,
    1081562, …). Keep fresh's body content (so user edits survive) but
    restore the macro shape from cached.

    ``rich_body`` / ``plain_body`` always reflect the source shape — fresh
    can't tell ``<ac:rich-text-body>`` apart from "no body" in the
    confluence-macro fence form.
    """
    updates["body"] = _reattach_blocks(fresh.body, cached.body)
    if not fresh.name:
        updates["name"] = cached.name
    if not fresh.params and cached.params:
        updates["params"] = dict(cached.params)
    updates["rich_body"] = cached.rich_body
    if cached.plain_body is not None and fresh.plain_body is None:
        updates["plain_body"] = cached.plain_body
    _graft_body_ws(fresh, cached, updates)


def _graft_table_block(fresh: Table, cached: Table, updates: dict[str, Any]) -> None:
    updates["rows"] = [
        _reattach_table_row(f, cached.rows[i]) if i < len(cached.rows) else f
        for i, f in enumerate(fresh.rows)
    ]


def _graft_layout_block(fresh: Layout, cached: Layout, updates: dict[str, Any]) -> None:
    updates["sections"] = [
        _reattach_layout_section(f, cached.sections[i]) if i < len(cached.sections) else f
        for i, f in enumerate(fresh.sections)
    ]


def _graft_heading_block(fresh: Heading, cached: Heading, updates: dict[str, Any]) -> None:
    if fresh.level == cached.level:
        updates["inlines"] = _reattach_or_replace_inlines(fresh.inlines, cached.inlines)


def _graft_paragraph_block(fresh: Paragraph, cached: Paragraph, updates: dict[str, Any]) -> None:
    updates["inlines"] = _reattach_or_replace_inlines(fresh.inlines, cached.inlines)


# Per-Block-kind grafts. Keyed by exact `type(fresh)`; safe because
# `_reattach_blocks` only calls `_reattach_block` after asserting
# `type(fnode) is type(cached[i])`, so the lookup never sees a mismatched
# pair. Adding a new container kind that needs special-cased reattach is
# one entry here, not another `elif` in the dispatcher.
_TYPED_REATTACH: dict[type[Block], Callable[[Any, Any, dict[str, Any]], None]] = {
    BulletList: _graft_list_block,
    OrderedList: _graft_list_block,
    BlockQuote: _graft_blockquote_block,
    Callout: _graft_callout_block,
    ConfluenceMacro: _graft_macro_block,
    Table: _graft_table_block,
    Layout: _graft_layout_block,
    Heading: _graft_heading_block,
    Paragraph: _graft_paragraph_block,
}


def _dispatch_typed_reattach(fresh: Block, cached: Block, updates: dict[str, Any]) -> None:
    """Route to the per-kind graft via the `_TYPED_REATTACH` table.

    Relies on the same-type precondition `_reattach_blocks` enforces.
    """
    graft = _TYPED_REATTACH.get(type(fresh))
    if graft is not None:
        graft(fresh, cached, updates)


def _reattach_block(fresh: Block, cached: Block) -> Block:
    updates: dict[str, Any] = {
        "node_id": cached.node_id or fresh.node_id,
    }
    _graft_common_node_metadata(fresh, cached, updates)
    _graft_attributes_block(fresh, cached, updates)
    _dispatch_typed_reattach(fresh, cached, updates)
    _graft_code_block_typed_fields(fresh, cached, updates)
    return replace(fresh, **updates)


def _flat_text(tokens: list[Inline]) -> str:
    """Concatenate the user-visible text of an inline list.

    Matches the collapse_soft_breaks + normalise_whitespace passes so a
    fresh inline list parsed from canonical markdown compares equal to the
    cached storage-derived inline list. Used by reattach to detect "same
    content, different inline structure" — the markdown leg drops
    SoftBreak / collapses runs of whitespace.
    """
    parts: list[str] = []
    for tok in tokens:
        if isinstance(tok, (Text, Code)):
            parts.append(tok.content)
        elif isinstance(tok, (Strong, Emph, Strikethrough, Link)):
            parts.append(_flat_text(tok.tokens))
        elif isinstance(tok, ConfluenceLink):
            parts.append(_flat_text(tok.body_tokens))
        elif isinstance(tok, LineBreak):
            parts.append("\n")
        elif isinstance(tok, SoftBreak):
            parts.append(" ")
    return " ".join("".join(parts).split())


def _reattach_or_replace_inlines(fresh: list[Inline], cached: list[Inline]) -> list[Inline]:
    """Reattach inline metadata; if flat-text matches end-to-end, prefer the
    cached inline list outright. This recovers the R3 round-trip case where
    `parse_markdown` collapsed SoftBreaks that the cached IR_a still carries.
    """
    if _flat_text(fresh) == _flat_text(cached):
        return list(cached)
    return _reattach_inlines(fresh, cached)


def _reattach_list_item(fresh: ListItem, cached: ListItem) -> ListItem:
    updates: dict[str, Any] = {
        "node_id": cached.node_id or fresh.node_id,
        "children": _reattach_blocks(fresh.children, cached.children),
    }
    if cached.attributes:
        merged = _merge_attributes_onto(fresh.attributes, cached.attributes)
        if merged is not None:
            updates["attributes"] = merged
    return replace(fresh, **updates)


def _reattach_table_row(fresh: TableRow, cached: TableRow) -> TableRow:
    cells = [
        _reattach_table_cell(f, cached.cells[i]) if i < len(cached.cells) else f
        for i, f in enumerate(fresh.cells)
    ]
    updates: dict[str, Any] = {
        "cells": cells,
    }
    if cached.attributes:
        merged = _merge_attributes_onto(fresh.attributes, cached.attributes)
        if merged is not None:
            updates["attributes"] = merged
    return replace(fresh, **updates)


# Row/colspan are excluded from attributes grafting: markdown tables do not
# carry them, and grafting them would create a mismatch between `attributes`
# (grafted colspan=3) and the typed `colspan` field (1, markdown default).
_CELL_SPAN_ATTRS: frozenset[str] = frozenset({"rowspan", "colspan"})


def _reattach_table_cell(fresh: TableCell, cached: TableCell) -> TableCell:
    updates: dict[str, Any] = {
        "children": _reattach_blocks(fresh.children, cached.children),
    }
    if cached.attributes:
        merged = _merge_attributes_onto(fresh.attributes, cached.attributes, skip=_CELL_SPAN_ATTRS)
        if merged is not None:
            updates["attributes"] = merged
    return replace(fresh, **updates)


# `ac:type` is excluded from attributes grafting: markdown carries the
# section type in the fenced-div `layout_type` field, so grafting the cached
# one would create a mismatch between `attributes` (grafted ac:type) and the
# typed `layout_type` field — and the storage writer prefers `attributes`.
# An authored type change would be silently dropped, and inserting or
# removing a section would shift every later section onto the wrong type.
_SECTION_TYPE_ATTRS: frozenset[str] = frozenset({"ac:type"})


def _reattach_layout_section(fresh: LayoutSection, cached: LayoutSection) -> LayoutSection:
    cells = [
        _reattach_layout_cell(f, cached.cells[i]) if i < len(cached.cells) else f
        for i, f in enumerate(fresh.cells)
    ]
    # The markdown leg only carries `layout_type` in the fenced-div info
    # string; `ac:local-id`, `ac:breakout-mode`, `ac:breakout-width` etc.
    # are dropped. Graft them back from the cached IR so the storage
    # writer can re-emit them.
    updates: dict[str, Any] = {
        "cells": cells,
    }
    if cached.attributes:
        merged_b = _merge_attributes_onto(
            fresh.attributes, cached.attributes, skip=_SECTION_TYPE_ATTRS
        )
        if merged_b is not None:
            updates["attributes"] = merged_b
    return replace(fresh, **updates)


def _reattach_layout_cell(fresh: LayoutCell, cached: LayoutCell) -> LayoutCell:
    # Graft cached attributes back. The markdown `:::::layout-cell` fence
    # carries no attributes today.
    updates: dict[str, Any] = {
        "children": _reattach_blocks(fresh.children, cached.children),
    }
    if cached.attributes:
        merged_b = _merge_attributes_onto(fresh.attributes, cached.attributes)
        if merged_b is not None:
            updates["attributes"] = merged_b
    return replace(fresh, **updates)


def _graft_inline_metadata(ftok: Any, ctok: Any) -> dict[str, Any]:
    """Build an updates dict grafting attributes and origin from ctok to ftok."""
    updates: dict[str, Any] = {}
    _graft_attributes(ftok, ctok, updates)
    _graft_origin(ftok, ctok, updates)
    return updates


def _graft_attributes(ftok: Any, ctok: Any, updates: dict[str, Any]) -> None:
    c_attributes = getattr(ctok, "attributes", None)
    f_attributes = getattr(ftok, "attributes", None)
    if not isinstance(c_attributes, dict) or not isinstance(f_attributes, dict):
        return
    if not c_attributes:
        return
    merged = _merge_attributes_onto(
        cast("dict[str, str]", f_attributes),
        cast("dict[str, str]", c_attributes),
    )
    if merged is not None:
        updates["attributes"] = merged


def _graft_origin(ftok: Any, ctok: Any, updates: dict[str, Any]) -> None:
    c_origin = getattr(ctok, "origin", None)
    if c_origin is None or not hasattr(ftok, "origin"):
        return
    c_content = getattr(ctok, "content", None)
    f_content = getattr(ftok, "content", None)
    # entity_form keys are codepoint offsets into the cached content string.
    # Grafting them onto fresh content of a different length splices entities
    # at the wrong place (e.g. fixture 1212604: cached Text " — exercise…"
    # has entity_form {1: "&mdash;"}; fresh "shell output" with that origin
    # renders as "s&mdash;ell output"). Strip entity_form when contents differ
    # — offsets are only meaningful for the content they were calibrated on.
    if (
        c_origin.entity_form
        and isinstance(c_content, str)
        and isinstance(f_content, str)
        and c_content != f_content
    ):
        updates["origin"] = replace(c_origin, entity_form={})
    else:
        updates["origin"] = c_origin


def _reattach_inlines(fresh: list[Inline], cached: list[Inline]) -> list[Inline]:
    """Inline-level reattach: graft identity + passthrough fields onto same-shape pairs."""
    out: list[Inline] = []
    for i, ftok in enumerate(fresh):
        if i < len(cached) and type(ftok) is type(cached[i]) and is_dataclass(ftok):
            updates = _graft_inline_metadata(ftok, cached[i])
            if updates:
                out.append(replace(ftok, **updates))
                continue
        out.append(ftok)
    return out
