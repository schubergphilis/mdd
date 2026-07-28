"""Table rendering: ``<table>`` / ``<thead>`` / ``<tbody>`` / ``<tr>`` / ``<th|td>``."""

from __future__ import annotations

from typing import Literal

from mdd.ir.nodes import Paragraph, Table, TableCell, TableRow

from .entities import emit_attrs
from .inlines import render_inlines


def render_table(
    block: Table,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    out.append(f"<table{emit_attrs(block.attributes)}>\n")
    head_rows: list[TableRow] = []
    body_rows: list[TableRow] = []
    if block.has_header and block.rows:
        if any(c.header for c in block.rows[0].cells):
            head_rows.append(block.rows[0])
            body_rows.extend(block.rows[1:])
        else:
            body_rows = list(block.rows)
    else:
        body_rows = list(block.rows)
    align: list[str] = list(block.align)
    if head_rows:
        out.append("<thead>\n")
        for row in head_rows:
            _render_table_row(row, out, mode=mode, align=align)
            out.append("\n")
        out.append("</thead>\n")
    if body_rows:
        out.append("<tbody>\n")
        for row in body_rows:
            _render_table_row(row, out, mode=mode, align=align)
            out.append("\n")
        out.append("</tbody>\n")
    out.append("</table>")


_ALIGN_STYLE: dict[str, str] = {
    "left": "text-align: left;",
    "right": "text-align: right;",
    "center": "text-align: center;",
}


def _column_align(align: list[str] | None, col: int) -> str:
    """Return the per-column alignment, defaulting to ``"default"`` when the
    column index falls outside the configured list."""
    if align is None or col >= len(align):
        return "default"
    return align[col]


def _style_inject_for(cell: TableCell, col_align: str) -> str:
    """Build the inline ``style="text-align: …"`` attribute fragment to
    inject when the table-level alignment applies and the cell has not
    already pinned its own ``style``. Returns an empty string when no
    injection is needed."""
    if col_align not in _ALIGN_STYLE or "style" in cell.attributes:
        return ""
    return f' style="{_ALIGN_STYLE[col_align]}"'


def _render_cell_body(
    cell: TableCell,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"],
) -> None:
    """Render a cell's body. A single attribute-less ``Paragraph`` child is
    flattened to bare inline content (matches Confluence's storage shape);
    everything else delegates to the generic block renderer."""
    from .blocks import render_block  # break the table.py ↔ blocks.py cycle  # noqa: PLC0415

    if (
        len(cell.children) == 1
        and isinstance(cell.children[0], Paragraph)
        and not cell.children[0].attributes
    ):
        render_inlines(cell.children[0].inlines, out, mode=mode)
        return
    for child in cell.children:
        render_block(child, out, mode=mode)


def _render_table_row(
    row: TableRow,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
    align: list[str] | None = None,
) -> None:
    out.append(f"<tr{emit_attrs(row.attributes)}>\n")
    col = 0
    for cell in row.cells:
        tag = "th" if cell.header else "td"
        # Honour the table's per-column alignment when the cell's own
        # ``style`` attr does not already pin one. Confluence storage
        # carries alignment via ``style="text-align: …"`` on each cell.
        style_inject = _style_inject_for(cell, _column_align(align, col))
        out.append(f"<{tag}{style_inject}{emit_attrs(cell.attributes)}>")
        col += cell.colspan
        _render_cell_body(cell, out, mode=mode)
        out.append(f"</{tag}>\n")
    out.append("</tr>")
