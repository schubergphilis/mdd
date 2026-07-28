"""Block-level element handlers: paragraph, heading, list, table, layout, …."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from lxml import etree

from mdd.ir.nodes import (
    Block,
    BlockQuote,
    BulletList,
    CodeBlock,
    Heading,
    HorizontalRule,
    Layout,
    LayoutCell,
    LayoutSection,
    ListItem,
    OrderedList,
    Paragraph,
    RawBlock,
)

from ..attrs import all_attrs_ordered
from ..fallback import block_fallback, serialize_raw
from ..macros import read_structured_macro
from ._namespaces import (
    AC,
    AC_LAYOUT,
    AC_LAYOUT_CELL,
    AC_LAYOUT_SECTION,
    AC_STRUCTURED_MACRO,
    AC_TASK,
    AC_TASK_BODY,
    AC_TASK_ID,
    AC_TASK_LIST,
    AC_TASK_STATUS,
    HEADING_TAGS,
)
from .inline import read_inline_children
from .listing import read_list_items
from .table import read_table

if TYPE_CHECKING:
    from collections.abc import Callable

    from mdd.ir.fallback import IRContext


def _read_heading(node: Any, ctx: IRContext | None) -> list[Block]:
    tag = node.tag
    return [
        Heading(
            level=HEADING_TAGS[tag],
            inlines=read_inline_children(node, ctx),
            attributes=all_attrs_ordered(node),
        )
    ]


def _read_paragraph(node: Any, ctx: IRContext | None) -> list[Block]:
    # Spike fix 1: preserve empty <p> nodes rather than dropping them.
    # Empty paragraphs are meaningful in Confluence (they carry structural
    # position in the page) and must survive the reader for round-trips.
    return [
        Paragraph(
            inlines=read_inline_children(node, ctx),
            attributes=all_attrs_ordered(node),
        )
    ]


def _read_bullet_list(node: Any, ctx: IRContext | None) -> list[Block]:
    # Track whether the source had inter-tag whitespace between `<ul>`
    # and the first `<li>` (and between `</li>` siblings). lxml drops
    # this in the tree; the writer needs the hint to round-trip the
    # compact `<ul><li>` shape vs the canonical `<ul>\n<li>` shape.
    compact = not bool(node.text)
    return [
        BulletList(
            items=read_list_items(node, ctx),
            compact=compact,
            attributes=all_attrs_ordered(node),
        )
    ]


def _read_ordered_list(node: Any, ctx: IRContext | None) -> list[Block]:
    start_attr = node.get("start")
    start = int(start_attr) if start_attr and start_attr.isdigit() else 1
    # Track whether source had an explicit start attribute; preserving-mode
    # writer uses this to avoid the spike-fix-#2 default `start="1"`
    # injection when the source omitted it.
    omit_start = start_attr is None
    compact = not bool(node.text)
    return [
        OrderedList(
            items=read_list_items(node, ctx),
            start=start,
            compact=compact,
            omit_start=omit_start,
            attributes=all_attrs_ordered(node, skip=("start",) if omit_start else ()),
        )
    ]


def _read_blockquote(node: Any, ctx: IRContext | None) -> list[Block]:
    from . import read_blocks_from_container  # noqa: PLC0415

    return [
        BlockQuote(
            children=read_blocks_from_container(node, ctx),
            attributes=all_attrs_ordered(node),
        )
    ]


def _read_hr(node: Any, _ctx: IRContext | None) -> list[Block]:
    return [HorizontalRule(attributes=all_attrs_ordered(node))]


def _read_pre_code(code_node: Any) -> tuple[str, str | None]:
    """Read a ``<code>`` child of ``<pre>``; return ``(content, language)``."""
    content = (code_node.text or "") + "".join(
        etree.tostring(g, encoding="unicode") for g in code_node
    )
    m = re.match(r"language-(\S+)", code_node.get("class") or "")
    return content, (m.group(1) if m else None)


def _read_pre(node: Any, _ctx: IRContext | None) -> list[Block]:
    content = ""
    language: str | None = None
    has_code_wrapper = False
    for ch in node:
        if isinstance(ch.tag, str) and ch.tag == "code":
            has_code_wrapper = True
            content, language = _read_pre_code(ch)
            break
    if not has_code_wrapper:
        content = node.text or ""
    return [
        CodeBlock(
            content=content,
            language=language,
            no_wrapper=not has_code_wrapper,
            attributes=all_attrs_ordered(node),
        )
    ]


def _read_table_block(node: Any, ctx: IRContext | None) -> list[Block]:
    table = read_table(node, ctx)
    if any(c.rowspan > 1 or c.colspan > 1 for r in table.rows for c in r.cells):
        return [RawBlock(content=serialize_raw(node), attributes=table.attributes)]
    return [table]


def _read_div(node: Any, ctx: IRContext | None) -> list[Block]:
    from . import read_blocks_from_container  # noqa: PLC0415

    return read_blocks_from_container(node, ctx)


def _read_layout_wrapper(node: Any, ctx: IRContext | None) -> list[Block]:
    return [_read_layout(node, ctx)]


def _read_structured_macro_wrapper(node: Any, ctx: IRContext | None) -> list[Block]:
    from . import read_blocks_from_container  # noqa: PLC0415

    def _read_blocks_with_ctx(n: Any) -> list[Block]:
        return read_blocks_from_container(n, ctx)

    return read_structured_macro(node, _read_blocks_with_ctx)


def _read_task_list_wrapper(node: Any, ctx: IRContext | None) -> list[Block]:
    return [_read_task_list(node, ctx)]


# Single-tag block readers. Heading tags share `_read_heading` via the
# `HEADING_TAGS` mapping. AC_LAYOUT_SECTION / AC_LAYOUT_CELL both flatten
# their children via `_read_div`-style passthrough.
_BLOCK_READERS: dict[str, Callable[[Any, IRContext | None], list[Block]]] = {
    "p": _read_paragraph,
    "ul": _read_bullet_list,
    "ol": _read_ordered_list,
    "blockquote": _read_blockquote,
    "hr": _read_hr,
    "pre": _read_pre,
    "table": _read_table_block,
    "div": _read_div,
    AC_LAYOUT: _read_layout_wrapper,
    AC_LAYOUT_SECTION: _read_div,
    AC_LAYOUT_CELL: _read_div,
    AC_STRUCTURED_MACRO: _read_structured_macro_wrapper,
    AC_TASK_LIST: _read_task_list_wrapper,
}


def read_block(node: Any, ctx: IRContext | None = None) -> list[Block]:
    """Read one block-level element into IR nodes. May return >1 for layouts."""
    tag = node.tag if isinstance(node.tag, str) else ""
    if tag in HEADING_TAGS:
        return _read_heading(node, ctx)
    reader = _BLOCK_READERS.get(tag)
    if reader is not None:
        return reader(node, ctx)
    return [block_fallback(node, ctx=ctx, reason=f"unrecognised block element: {tag}")]


def _parse_task_fields(task_node: Any) -> tuple[str, str, Any]:
    """Walk an ``<ac:task>``'s direct children and return
    ``(task_id, status_text, body_node)``. Missing children stay as the
    empty-string / ``None`` defaults the caller expects."""
    task_id = ""
    status_text = ""
    body_node: Any = None
    for sub in task_node:
        sub_tag = sub.tag if isinstance(sub.tag, str) else ""
        if sub_tag == AC_TASK_ID:
            task_id = (sub.text or "").strip()
        elif sub_tag == AC_TASK_STATUS:
            status_text = (sub.text or "").strip()
        elif sub_tag == AC_TASK_BODY:
            body_node = sub
    return task_id, status_text, body_node


def _read_task_body(body_node: Any, ctx: IRContext | None) -> list[Block]:
    """Read the body of an ``<ac:task-body>``: inline-only bodies become a
    single ``Paragraph``; mixed-content bodies use the generic block reader,
    falling back to a one-paragraph wrap when the block reader returns
    nothing but inlines were present."""
    from . import read_blocks_from_container  # noqa: PLC0415

    inline_kids = read_inline_children(body_node, ctx)
    body_is_inline_only = bool(inline_kids) and not any(
        isinstance(g.tag, str) and g.tag != "" for g in body_node
    )
    if body_is_inline_only:
        return [Paragraph(inlines=inline_kids)]
    children = read_blocks_from_container(body_node, ctx)
    if not children and inline_kids:
        return [Paragraph(inlines=inline_kids)]
    return children


def _read_task_item(task_node: Any, ctx: IRContext | None) -> ListItem:
    """Read one ``<ac:task>`` into a ``ListItem`` carrying its task status
    and (optional) ``ac:task-id`` on the attributes map."""
    task_id, status_text, body_node = _parse_task_fields(task_node)
    item_attributes: dict[str, str] = {"task": "done" if status_text == "complete" else "open"}
    if task_id:
        item_attributes["ac:task-id"] = task_id
    children = _read_task_body(body_node, ctx) if body_node is not None else []
    return ListItem(children=children, attributes=item_attributes)


def _read_task_list(node: Any, ctx: IRContext | None = None) -> BulletList:
    """Read an ``<ac:task-list>`` into a ``BulletList`` of task ``ListItem``s.

    Pairs with the writer's ``_render_task_list``.  Each ``<ac:task>``
    becomes a ``ListItem(attrs={"task": "open"|"done"})`` whose body holds
    the ``<ac:task-body>`` contents as a single paragraph (when the body is
    inline-only) or as block children.
    """
    items = [
        _read_task_item(child, ctx)
        for child in node
        if isinstance(child.tag, str) and child.tag == AC_TASK
    ]
    return BulletList(
        items=items,
        attributes=all_attrs_ordered(node),
    )


def _read_layout_cell(cell_node: Any, ctx: IRContext | None) -> LayoutCell:
    from . import read_blocks_from_container  # noqa: PLC0415

    return LayoutCell(
        children=read_blocks_from_container(cell_node, ctx),
        attributes=all_attrs_ordered(cell_node),
    )


def _read_layout_section(section_node: Any, ctx: IRContext | None) -> LayoutSection:
    layout_type = section_node.get(f"{{{AC}}}type") or section_node.get("ac:type") or "default"
    cells: list[LayoutCell] = [
        _read_layout_cell(cell_node, ctx)
        for cell_node in section_node
        if isinstance(cell_node.tag, str) and cell_node.tag == AC_LAYOUT_CELL
    ]
    return LayoutSection(
        layout_type=layout_type,
        cells=cells,
        attributes=all_attrs_ordered(section_node),
    )


def _read_layout(node: Any, ctx: IRContext | None = None) -> Layout:
    sections: list[LayoutSection] = [
        _read_layout_section(child, ctx)
        for child in node
        if isinstance(child.tag, str) and child.tag == AC_LAYOUT_SECTION
    ]
    return Layout(
        sections=sections,
        attributes=all_attrs_ordered(node),
    )
