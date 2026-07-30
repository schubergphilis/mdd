"""Block-level consumption: markdown-it token stream → IR ``Block`` nodes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mdd.ir.fallback import emit_block_fallback
from mdd.ir.nodes import (
    Block,
    BlockQuote,
    BulletList,
    Callout,
    CodeBlock,
    ConfluenceMacro,
    Heading,
    HorizontalRule,
    OrderedList,
    Paragraph,
    RawBlock,
)

from .inlines import consume_inlines
from .layout import consume_layout, parse_attr_block
from .listing import consume_list
from .macros import split_inline_macros
from .table import consume_table

if TYPE_CHECKING:
    from collections.abc import Callable

    from markdown_it.token import Token

    from mdd.ir.fallback import IRContext


_CALLOUT_KINDS = frozenset(("tip", "info", "note", "warning", "panel"))


def _consume_heading(tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None) -> int:
    tok = tokens[i]
    level = int(tok.tag[1])
    inlines = consume_inlines(tokens[i + 1], ctx)
    out.append(Heading(level=level, inlines=inlines))
    return i + 3


def _consume_paragraph(tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None) -> int:
    inlines = consume_inlines(tokens[i + 1], ctx)
    inlines = split_inline_macros(inlines, ctx)
    out.append(Paragraph(inlines=inlines))
    return i + 3


def _consume_bullet_list(
    tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None
) -> int:
    items, j = consume_list(tokens, i, ctx)
    tight = tokens[i].attrGet("class") == "contains-task-list"
    out.append(BulletList(items=items, tight=tight))
    return j


def _consume_ordered_list(
    tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None
) -> int:
    start_attr = tokens[i].attrGet("start")
    start = int(start_attr) if start_attr else 1
    items, j = consume_list(tokens, i, ctx)
    out.append(OrderedList(items=items, start=start))
    return j


def _consume_blockquote(
    tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None
) -> int:
    nested: list[Block] = []
    i += 1
    while i < len(tokens) and tokens[i].type != "blockquote_close":
        i = consume_block(tokens, i, nested, ctx)
    out.append(BlockQuote(children=nested))
    return i + 1


def _consume_hr(tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None) -> int:
    del tokens, ctx
    out.append(HorizontalRule())
    return i + 1


def _consume_fence(tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None) -> int:
    tok = tokens[i]
    info = tok.info.strip()
    content = tok.content.removesuffix("\n")
    if info == "confluence-xml":
        out.append(
            emit_block_fallback(
                content,
                source_format="confluence-storage",
                reason="confluence-xml fence",
                ctx=ctx,
                format_override="confluence-storage",
            )
        )
    else:
        out.append(CodeBlock(content=content, language=info or None))
    return i + 1


def _consume_code_block(
    tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None
) -> int:
    del ctx
    out.append(CodeBlock(content=tokens[i].content.removesuffix("\n")))
    return i + 1


def _consume_table(tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None) -> int:
    table, j = consume_table(tokens, i, ctx)
    out.append(table)
    return j


def _consume_html_block(
    tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None
) -> int:
    out.append(
        emit_block_fallback(
            tokens[i].content.rstrip("\n"),
            source_format="html",
            reason="html_block token",
            ctx=ctx,
            format_override="html",
        )
    )
    return i + 1


_BLOCK_CONSUMERS: dict[str, Callable[[list[Token], int, list[Block], IRContext | None], int]] = {
    "heading_open": _consume_heading,
    "paragraph_open": _consume_paragraph,
    "bullet_list_open": _consume_bullet_list,
    "ordered_list_open": _consume_ordered_list,
    "blockquote_open": _consume_blockquote,
    "hr": _consume_hr,
    "fence": _consume_fence,
    "code_block": _consume_code_block,
    "table_open": _consume_table,
    "html_block": _consume_html_block,
}


def consume_block(tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None) -> int:
    t = tokens[i].type
    handler = _BLOCK_CONSUMERS.get(t)
    if handler is not None:
        return handler(tokens, i, out, ctx)
    if t.startswith("container_") and t.endswith("_open"):
        return _consume_container(tokens, i, out, ctx)
    return i + 1


def _consume_container(tokens: list[Token], i: int, out: list[Block], ctx: IRContext | None) -> int:
    open_tok = tokens[i]
    open_type = open_tok.type
    close_type = open_type.replace("_open", "_close")
    name = open_type[len("container_") : -len("_open")]
    info = open_tok.info.strip()

    # Layout containers: `:::layout` wraps `::::layout-section
    # layout_type="..."` blocks, each containing `:::::layout-cell` blocks.
    # Handle these via a dedicated consumer to preserve the Layout / LayoutSection
    # / LayoutCell structure rather than collapsing them into generic raw fallbacks.
    if name == "layout":
        return consume_layout(tokens, i, out, ctx)

    params = parse_attr_block(info)

    nested: list[Block] = []
    i += 1
    while i < len(tokens) and tokens[i].type != close_type:
        i = consume_block(tokens, i, nested, ctx)

    if name.startswith("callout-"):
        kind = name[len("callout-") :]
        if kind in _CALLOUT_KINDS:
            out.append(Callout(kind=kind, body=nested, params=params))  # pyright: ignore[reportArgumentType]
        else:
            raw = emit_block_fallback(
                info,
                source_format="markdown",
                reason=f"unknown callout kind: {kind}",
                ctx=ctx,
            )
            out.append(raw)
    elif name == "confluence-macro":
        macro_name = params.pop("name", "")
        rich = True
        plain_body: str | None = None
        if all(isinstance(b, RawBlock) for b in nested) and nested:
            plain_body = "\n".join(b.content for b in nested if isinstance(b, RawBlock))
            rich = False
            nested = []
        out.append(
            ConfluenceMacro(
                name=macro_name,
                params=params,
                body=nested,
                plain_body=plain_body,
                rich_body=rich,
            )
        )
    else:
        raw = emit_block_fallback(
            info,
            source_format="markdown",
            reason=f"unknown container: {name}",
            ctx=ctx,
        )
        out.append(raw)

    return i + 1
