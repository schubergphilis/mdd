"""Table consumption: ``table_open`` … ``table_close`` runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mdd.ir.nodes import Paragraph, Table, TableCell, TableRow

from .inlines import consume_inlines
from .macros import split_inline_macros

if TYPE_CHECKING:
    from markdown_it.token import Token

    from mdd.ir.fallback import IRContext


def consume_table(tokens: list[Token], i: int, ctx: IRContext | None) -> tuple[Table, int]:
    rows: list[TableRow] = []
    in_header = False
    has_header = False
    cells: list[TableCell] = []
    align: list[str] = []
    i += 1
    while i < len(tokens) and tokens[i].type != "table_close":
        t = tokens[i].type
        if t == "thead_open":
            in_header = True
            has_header = True
        elif t == "thead_close":
            in_header = False
        elif t in ("tbody_open", "tbody_close"):
            pass
        elif t == "tr_open":
            cells = []
        elif t in ("td_open", "th_open"):
            header = t == "th_open" or in_header
            style = str(tokens[i].attrGet("style") or "")
            col_align = _parse_align(style)
            if in_header and t == "th_open":
                align.append(col_align)
            inline_tok = tokens[i + 1]
            inlines = consume_inlines(inline_tok, ctx)
            inlines = split_inline_macros(inlines, ctx)
            cells.append(
                TableCell(
                    children=[Paragraph(inlines=inlines)] if inlines else [],
                    header=header,
                )
            )
            i += 2
        elif t == "tr_close":
            rows.append(TableRow(cells=cells))
        i += 1
    return Table(rows=rows, has_header=has_header, align=align), i + 1  # pyright: ignore[reportArgumentType]


def _parse_align(style: str) -> str:
    if "text-align:right" in style or "text-align: right" in style:
        return "right"
    if "text-align:center" in style or "text-align: center" in style:
        return "center"
    if "text-align:left" in style or "text-align: left" in style:
        return "left"
    return "default"
