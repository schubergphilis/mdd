"""``<ac:layout>`` / ``<ac:layout-section>`` / ``<ac:layout-cell>`` rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from xml.sax.saxutils import quoteattr

from .entities import emit_attrs

if TYPE_CHECKING:
    from mdd.ir.nodes import Layout, LayoutCell, LayoutSection


def render_layout(
    block: Layout,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    out.append(f"<ac:layout{emit_attrs(block.attributes)}>")
    for section in block.sections:
        _render_layout_section(section, out, mode=mode)
    out.append("</ac:layout>")


def _render_layout_section(
    section: LayoutSection,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    # `attributes` has all source-order attrs (ac:type, ac:breakout-mode,
    # ac:local-id, …) when the node came from storage or was reattached.
    # For markdown-sourced sections (attributes empty or missing ac:type),
    # fall back to the typed `layout_type` field.
    if "ac:type" not in section.attributes:
        type_attr = f" ac:type={quoteattr(section.layout_type)}"
        out.append(f"<ac:layout-section{type_attr}{emit_attrs(section.attributes)}>")
    else:
        out.append(f"<ac:layout-section{emit_attrs(section.attributes)}>")
    for cell in section.cells:
        _render_layout_cell(cell, out, mode=mode)
    out.append("</ac:layout-section>")


def _render_layout_cell(
    cell: LayoutCell,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    # Deferred import to break the layout.py ↔ blocks.py cycle.
    from .blocks import render_block  # noqa: PLC0415

    out.append(f"<ac:layout-cell{emit_attrs(cell.attributes)}>")
    for child in cell.children:
        render_block(child, out, mode=mode)
    out.append("</ac:layout-cell>")
