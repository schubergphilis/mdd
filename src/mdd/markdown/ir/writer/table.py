"""Table rendering for the IR → markdown writer (GFM + HTML fallback)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from mdd.ir.nodes import Block, Paragraph

from .inlines import render_inlines

if TYPE_CHECKING:
    from mdd.ir.nodes import Table, TableRow


_Mode = Literal["normalising", "preserving"]


def _render_cell_text(cell_children: list[Block], mode: _Mode) -> str:
    # Deferred import (PLC0415) to break the table <-> blocks cycle.
    from .blocks import render_block  # noqa: PLC0415

    if not cell_children:
        return ""
    bits: list[str] = []
    if len(cell_children) == 1 and isinstance(cell_children[0], Paragraph):
        render_inlines(cell_children[0].inlines, bits, mode=mode)
    else:
        for child in cell_children:
            inner: list[str] = []
            render_block(child, inner, indent="", mode=mode)
            bits.append("".join(inner).replace("\n", " "))
    return "".join(bits).replace("|", "\\|").strip()


def _render_pipe_row(row: TableRow, indent: str, mode: _Mode) -> str:
    cells = [_render_cell_text(c.children, mode) for c in row.cells]
    return f"{indent}| " + " | ".join(cells) + " |"


def _sep_cell(col: int, align: list[Literal["default", "left", "right", "center"]]) -> str:
    a: str = align[col] if col < len(align) else "default"
    if a == "left":
        return ":---"
    if a == "right":
        return "---:"
    if a == "center":
        return ":---:"
    return "---"


def render_table(
    block: Table,
    out: list[str],
    *,
    indent: str,
    mode: _Mode = "normalising",
) -> None:
    if not block.rows:
        return

    # If any cell has colspan/rowspan > 1, fall back to HTML table.
    if _has_merged_cells(block):
        _render_table_as_html(block, out, indent=indent, mode=mode)
        return

    header_row = block.rows[0]
    body_rows = block.rows[1:]
    width = max(len(r.cells) for r in block.rows)

    out.extend((_render_pipe_row(header_row, indent, mode), "\n"))
    out.append(f"{indent}| " + " | ".join(_sep_cell(c, block.align) for c in range(width)) + " |")
    for row in body_rows:
        out.extend(("\n", _render_pipe_row(row, indent, mode)))


def _has_merged_cells(block: Table) -> bool:
    for row in block.rows:
        for cell in row.cells:
            if cell.colspan > 1 or cell.rowspan > 1:
                return True
    return False


def _render_table_as_html(
    block: Table,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    # Deferred import (PLC0415) to break the table <-> blocks cycle.
    from .blocks import render_block  # noqa: PLC0415

    out.append(f"{indent}<table>\n")
    for row in block.rows:
        out.append(f"{indent}<tr>")
        for cell in row.cells:
            tag = "th" if cell.header else "td"
            attrs = ""
            if cell.colspan > 1:
                attrs += f' colspan="{cell.colspan}"'
            if cell.rowspan > 1:
                attrs += f' rowspan="{cell.rowspan}"'
            inner: list[str] = []
            for child in cell.children:
                render_block(child, inner, indent="", mode=mode)
            out.append(f"<{tag}{attrs}>{''.join(inner)}</{tag}>")
        out.append("</tr>\n")
    out.append(f"{indent}</table>")
