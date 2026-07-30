"""Layout-container consumption: ``container_layout_*`` runs and attr parsing."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from mdd.ir.nodes import Block, Layout, LayoutCell, LayoutSection

from .._patterns import ATTR_RE

if TYPE_CHECKING:
    from markdown_it.token import Token

    from mdd.ir.fallback import IRContext


def parse_attr_block(info: str) -> dict[str, str]:
    m = re.search(r"\{([^}]*)\}", info)
    if not m:
        return {}
    body = m.group(1)
    out: dict[str, str] = {}
    for m2 in ATTR_RE.finditer(body):
        key = m2.group(1)
        value = m2.group(2).replace('\\"', '"').replace("\\\\", "\\")
        out[key] = value
    return out


def parse_bare_attrs(info: str) -> dict[str, str]:
    """Parse a bare ``key="value" key="value"`` sequence (no ``{}`` wrapper)."""
    out: dict[str, str] = {}
    for m in ATTR_RE.finditer(info):
        key = m.group(1)
        value = m.group(2).replace('\\"', '"').replace("\\\\", "\\")
        out[key] = value
    return out


def consume_layout(tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None) -> int:
    """Consume a ``container_layout_open`` … ``container_layout_close`` block.

    Children are expected to be ``container_layout-section_*`` containers; any
    other content is dropped (the writer never emits anything else inside a
    layout).
    """
    close_type = "container_layout_close"
    sections: list[LayoutSection] = []
    i += 1
    while i < len(tokens) and tokens[i].type != close_type:
        t = tokens[i].type
        if t == "container_layout-section_open":
            section, i = _consume_layout_section(tokens, i, ctx)
            sections.append(section)
        else:
            # Unknown content inside layout — skip the single token (the
            # writer doesn't produce this shape).
            i += 1
    out.append(Layout(sections=sections))
    return i + 1


def _consume_layout_section(
    tokens: list[Token], i: int, ctx: IRContext | None
) -> tuple[LayoutSection, int]:
    """Consume one ``container_layout-section_*`` block.

    Reads ``layout_type="..."`` from the info string (bare key="value" syntax
    as emitted by the writer) and collects ``LayoutCell`` children.
    """
    open_tok = tokens[i]
    info = open_tok.info.strip()
    attrs = parse_bare_attrs(info)
    layout_type = attrs.get("layout_type", "")
    close_type = "container_layout-section_close"
    cells: list[LayoutCell] = []
    i += 1
    while i < len(tokens) and tokens[i].type != close_type:
        t = tokens[i].type
        if t == "container_layout-cell_open":
            cell, i = _consume_layout_cell(tokens, i, ctx)
            cells.append(cell)
        else:
            i += 1
    return LayoutSection(layout_type=layout_type, cells=cells), i + 1


def _consume_layout_cell(
    tokens: list[Token], i: int, ctx: IRContext | None
) -> tuple[LayoutCell, int]:
    """Consume one ``container_layout-cell_*`` block holding arbitrary blocks."""
    # Deferred import (PLC0415) to break the layout <-> blocks cycle.
    from .blocks import consume_block  # noqa: PLC0415

    close_type = "container_layout-cell_close"
    children: list[Block] = []
    i += 1
    while i < len(tokens) and tokens[i].type != close_type:
        i = consume_block(tokens, i, children, ctx)
    return LayoutCell(children=children), i + 1
