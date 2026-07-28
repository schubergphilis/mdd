"""Table element handler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from mdd.ir.nodes import Table, TableCell, TableRow

from ..attrs import all_attrs_ordered

if TYPE_CHECKING:
    from mdd.ir.fallback import IRContext


_TABLE_SECTION_TAGS = frozenset({"thead", "tbody", "tfoot"})


def _read_section_rows(
    section: Any, ctx: IRContext | None, *, default_header: bool
) -> list[TableRow]:
    """Read the ``<tr>`` children of a ``<thead>``/``<tbody>``/``<tfoot>``."""
    return [
        read_table_row(tr, ctx, default_header=default_header)
        for tr in section
        if isinstance(tr.tag, str) and tr.tag == "tr"
    ]


def read_table(node: Any, ctx: IRContext | None = None) -> Table:
    rows: list[TableRow] = []
    has_header = False
    for section in node:
        tag = section.tag if isinstance(section.tag, str) else ""
        if tag in _TABLE_SECTION_TAGS:
            section_is_head = tag == "thead"
            section_rows = _read_section_rows(section, ctx, default_header=section_is_head)
            if section_is_head and section_rows:
                # Original behaviour set has_header only when the section
                # contained at least one `<tr>`; an empty `<thead/>` does
                # not contribute. This matches the prior loop's flag flip
                # being inside the per-row branch.
                has_header = True
            rows.extend(section_rows)
        elif tag == "tr":
            rows.append(read_table_row(section, ctx))
        # `caption` / `colgroup` and unknown tags are deliberately skipped.
    has_header_final = has_header or any(any(c.header for c in r.cells) for r in rows)
    return Table(
        rows=rows,
        has_header=has_header_final,
        align=_table_align_from_first_row(rows),
        attributes=all_attrs_ordered(node),
    )


_TableAlign = Literal["default", "left", "right", "center"]


def _table_align_from_first_row(rows: list[TableRow]) -> list[_TableAlign]:
    """Derive per-column alignment from the ``style="text-align: …"`` attrs
    on the first row's cells.

    Markdown carries column alignment on the header row only, and Confluence
    storage emits the matching ``text-align`` style per cell; reading the
    first row's styles is sufficient to populate ``Table.align`` for both
    GFM-style alignment round-trips and the storage-writer side of R3.
    """
    if not rows:
        return []
    source_row = rows[0]
    align: list[_TableAlign] = []
    for cell in source_row.cells:
        style = cell.attributes.get("style", "")
        norm = style.replace(" ", "").lower()
        col: _TableAlign
        if "text-align:left" in norm:
            col = "left"
        elif "text-align:right" in norm:
            col = "right"
        elif "text-align:center" in norm:
            col = "center"
        else:
            col = "default"
        align.append(col)
        for _ in range(cell.colspan - 1):
            align.append(col)  # noqa: PERF401
    if all(a == "default" for a in align):
        return []
    return align


def read_table_row(
    node: Any, ctx: IRContext | None = None, *, default_header: bool = False
) -> TableRow:
    # Deferred import to break the elements/__init__.py ↔ table.py cycle.
    from . import read_blocks_from_container  # noqa: PLC0415

    cells: list[TableCell] = []
    for ch in node:
        tag = ch.tag if isinstance(ch.tag, str) else ""
        if tag in {"td", "th"}:
            is_header = tag == "th" or default_header
            rowspan = int(ch.get("rowspan", "1") or "1")
            colspan = int(ch.get("colspan", "1") or "1")
            cells.append(
                TableCell(
                    children=read_blocks_from_container(ch, ctx),
                    header=is_header,
                    rowspan=rowspan,
                    colspan=colspan,
                    attributes=all_attrs_ordered(ch),
                )
            )
    return TableRow(
        cells=cells,
        attributes=all_attrs_ordered(node),
    )
