"""Block-level IR → Confluence storage rendering and dispatch."""

from __future__ import annotations

from typing import Literal, cast
from xml.sax.saxutils import escape, quoteattr

from mdd.ir.nodes import (
    Block,
    BlockQuote,
    BulletList,
    Callout,
    CodeBlock,
    ConfluenceImage,
    ConfluenceLink,
    ConfluenceMacro,
    Heading,
    HorizontalRule,
    Layout,
    ListItem,
    OrderedList,
    Paragraph,
    RawBlock,
    Table,
)

from ..cdata import wrap as cdata_wrap
from .code import render_code_block
from .entities import emit_attrs
from .inlines import render_inlines
from .layout import render_layout
from .links import render_confluence_link
from .macros import render_confluence_image
from .table import render_table


def _render_heading(
    block: Heading,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    out.append(f"<h{block.level}{emit_attrs(block.attributes)}>")
    render_inlines(block.inlines, out, mode=mode)
    out.append(f"</h{block.level}>")


def _render_bullet_list(
    block: BulletList,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    # A BulletList whose items all carry the GFM task marker
    # (``attrs["task"] in {"open","done"}``) is the markdown-leg form
    # of a Confluence ``<ac:task-list>`` macro.  Translate so the
    # storage side gets the native task macro rather than a plain
    # ``<ul>``.  Mixed lists (some task, some plain) keep the ``<ul>``
    # form — Confluence has no way to mix native tasks with regular
    # list items inside a single list.
    if block.items and all(item.attributes.get("task") in {"open", "done"} for item in block.items):
        _render_task_list(block, out, mode=mode)
        return
    sep = "" if block.compact else "\n"
    out.append(f"<ul{emit_attrs(block.attributes)}>{sep}")
    for item in block.items:
        _render_list_item(item, out, mode=mode)
        out.append(sep)
    out.append("</ul>")


def _render_ordered_list(
    block: OrderedList,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    # Use typed fields: `omit_start` (source had no explicit `start`) and
    # `compact` (source had no inter-tag whitespace). When `start` is not
    # already in `attributes` (markdown-sourced list), emit it from the
    # typed `start` field so the value survives to storage.
    sep = "" if block.compact else "\n"
    if not block.omit_start and "start" not in block.attributes:
        out.append(f'<ol start="{block.start}"{emit_attrs(block.attributes)}>{sep}')
    else:
        out.append(f"<ol{emit_attrs(block.attributes)}>{sep}")
    for item in block.items:
        _render_list_item(item, out, mode=mode)
        out.append(sep)
    out.append("</ol>")


def _render_blockquote(
    block: BlockQuote,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    out.append(f"<blockquote{emit_attrs(block.attributes)}>\n")
    for i, child in enumerate(block.children):
        if i > 0:
            out.append("\n")
        render_block(child, out, mode=mode)
    out.append("\n</blockquote>")


def _render_hr(
    block: HorizontalRule,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> None:
    out.append(f"<hr{emit_attrs(block.attributes)} />")


def _render_paragraph(
    block: Paragraph,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    inlines = block.inlines
    # When a Paragraph wraps a single block-level ConfluenceLink (no ``<p>``
    # wrapper in the source — typically a standalone user mention) emit the
    # link bare. The reader sets ``block_level=True``; the writer reads that.
    if len(inlines) == 1 and isinstance(inlines[0], ConfluenceLink) and inlines[0].block_level:
        render_confluence_link(inlines[0], out, mode=mode)
        return
    # Same pattern for ``ConfluenceImage`` at block level — image-only
    # layout-cells use this shape.
    if inlines and all(isinstance(t, ConfluenceImage) and t.block_level for t in inlines):
        for tok in inlines:
            render_confluence_image(cast("ConfluenceImage", tok), out)
        return

    # Empty `<p />` self-closes the same way Confluence's own renderer
    # emits empty paragraphs in storage XHTML. The reader can't tell the
    # difference between `<p></p>` and `<p />` (lxml collapses both to a
    # childless element), so the writer always picks the self-closing
    # form when there are no inlines. Matches the corpus shape for
    # macro-trailing empty paragraphs (e.g. fixture 131332).
    if not inlines:
        out.append(f"<p{emit_attrs(block.attributes)} />")
        return
    out.append(f"<p{emit_attrs(block.attributes)}>")
    render_inlines(inlines, out, mode=mode)
    out.append("</p>")


def _render_list_item(
    item: ListItem,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    out.append(f"<li{emit_attrs(item.attributes)}>")
    children = list(item.children)
    if children and isinstance(children[0], Paragraph) and not children[0].attributes:
        render_inlines(children[0].inlines, out, mode=mode)
        rest = children[1:]
        if rest:
            # The list-item reader pulls trailing whitespace (e.g. "\n"
            # between "<li>text:\n<ol>") into the first Paragraph's text.
            # Avoid inserting a second newline that would double the
            # separator between the paragraph and the nested block.
            inlines_buf = "".join(out)
            ends_with_ws = inlines_buf and inlines_buf[-1].isspace()
            if not ends_with_ws:
                out.append("\n")
        for i, child in enumerate(rest):
            if i > 0:
                out.append("\n")
            render_block(child, out, mode=mode)
        out.append("\n</li>" if rest else "</li>")
        return
    for child in children:
        render_block(child, out, mode=mode)
    out.append("</li>")


def _render_task_list(
    block: BulletList,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    """Emit a ``BulletList`` of task items as ``<ac:task-list>``.

    Each ``ListItem`` whose ``attrs["task"]`` is ``"open"`` or ``"done"``
    becomes one ``<ac:task>`` with the matching ``<ac:task-status>`` and
    a ``<ac:task-body>`` carrying the item's body inlines.  Task IDs
    cached on ``identity["ac:task-id"]`` are restored; otherwise the
    writer assigns sequential 1-based IDs (matching Confluence's own
    task numbering).
    """
    out.append(f"<ac:task-list{emit_attrs(block.attributes)}>\n")
    for index, item in enumerate(block.items, start=1):
        task_id = item.attributes.get("ac:task-id") or str(index)
        status = "complete" if item.attributes.get("task") == "done" else "incomplete"
        out.append("<ac:task>")
        out.append(f"<ac:task-id>{escape(task_id)}</ac:task-id>")
        out.append(f"<ac:task-status>{status}</ac:task-status>")
        out.append("<ac:task-body>")
        # A task item typically holds a single paragraph; unwrap it the
        # same way ``_render_list_item`` does so the body stays inline.
        children = list(item.children)
        if children and isinstance(children[0], Paragraph) and not children[0].attributes:
            render_inlines(children[0].inlines, out, mode=mode)
            for child in children[1:]:
                render_block(child, out, mode=mode)
        else:
            for child in children:
                render_block(child, out, mode=mode)
        out.append("</ac:task-body>")
        out.append("</ac:task>\n")
    out.append("</ac:task-list>")


def _render_callout(
    block: Callout,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    # `attributes` has all source-order attrs (ac:name, ac:schema-version,
    # passthroughs, ac:local-id, ac:macro-id) when the node came from storage
    # or was reattached. For markdown-sourced callouts (attributes empty),
    # emit ac:name from the typed `kind` field as the sole attribute.
    if "ac:name" not in block.attributes:
        attrs_str = f" ac:name={quoteattr(block.kind)}"
    else:
        attrs_str = emit_attrs(block.attributes)
    out.append(f"<ac:structured-macro{attrs_str}>")
    if block.title is not None:
        out.append(f'<ac:parameter ac:name="title">{escape(block.title)}</ac:parameter>')
    for key, value in block.params.items():
        out.append(f"<ac:parameter ac:name={quoteattr(key)}>{escape(value)}</ac:parameter>")
    out.append("<ac:rich-text-body>")
    if block.body_leading_ws:
        out.append(block.body_leading_ws)
    for child in block.body:
        render_block(child, out, mode=mode)
    if block.body_trailing_ws:
        out.append(block.body_trailing_ws)
    out.append("</ac:rich-text-body>")
    out.append("</ac:structured-macro>")


def _render_confluence_macro(
    block: ConfluenceMacro,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    # `attributes` carries all source-order attrs (including ac:name,
    # ac:schema-version, passthroughs, ac:local-id, ac:macro-id) when the
    # node came from storage or was reattached. For markdown-sourced macros
    # (attributes empty), emit ac:name from the typed `name` field.
    if "ac:name" not in block.attributes:
        attrs_str = f" ac:name={quoteattr(block.name)}"
    else:
        attrs_str = emit_attrs(block.attributes)
    out.append(f"<ac:structured-macro{attrs_str}>")
    for key, value in block.params.items():
        out.append(f"<ac:parameter ac:name={quoteattr(key)}>{value}</ac:parameter>")
    # Spike fix 3: honour rich_body vs plain_body — don't emit
    # <ac:rich-text-body> when rich_body is False.
    if block.rich_body:
        out.append("<ac:rich-text-body>")
        if block.body_leading_ws:
            out.append(block.body_leading_ws)
        for child in block.body:
            render_block(child, out, mode=mode)
        if block.body_trailing_ws:
            out.append(block.body_trailing_ws)
        out.append("</ac:rich-text-body>")
    elif block.plain_body is not None:
        out.append(f"<ac:plain-text-body>{cdata_wrap(block.plain_body)}</ac:plain-text-body>")
    out.append("</ac:structured-macro>")


def _render_raw_block(
    block: RawBlock,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    # In preserving mode, emit the verbatim source bytes when available.
    # If the reader truncated raw_bytes (over ORIGIN_RAW_BYTES_CAP), fall
    # through to the canonical render below.
    if (
        mode == "preserving"
        and block.origin is not None
        and block.origin.raw_bytes
        and not block.origin.raw_bytes_truncated
    ):
        out.append(block.origin.raw_bytes.decode("utf-8"))
        return
    if block.format in {"confluence-storage", "xhtml", "html"}:
        # CommonMark "raw HTML blocks" (e.g. ``<details>…</details>``) are
        # valid Confluence storage as long as they're well-formed XML — the
        # markdown reader captured them verbatim, so the storage writer must
        # echo them. The previous ``<pre>``-wrap entity-escaped the content
        # and made the block visible as code, which is a fidelity loss for
        # any HTML element Confluence renders natively.
        out.append(block.content)
        return
    out.append(f"<!-- raw:{block.format} --><pre>{escape(block.content)}</pre>")


_BLOCK_RENDERERS: dict[type, object] = {
    Heading: _render_heading,
    Paragraph: _render_paragraph,
    BulletList: _render_bullet_list,
    OrderedList: _render_ordered_list,
    BlockQuote: _render_blockquote,
    HorizontalRule: _render_hr,
    CodeBlock: render_code_block,
    Table: render_table,
    Callout: _render_callout,
    ConfluenceMacro: _render_confluence_macro,
    Layout: render_layout,
}


def render_block(
    block: Block, out: list[str], *, mode: Literal["normalising", "preserving"] = "normalising"
) -> None:
    renderer = _BLOCK_RENDERERS.get(type(block))
    if renderer is None:
        _render_raw_block(cast("RawBlock", block), out, mode=mode)
        return
    renderer(block, out, mode=mode)  # pyright: ignore[reportCallIssue]
