"""Markdown → IR reader.

Entry point: ``parse_markdown(md_text, *, ctx=None) -> Document``.

Walks the markdown-it-py token stream produced by ``flavour.build_md()``
into IR nodes. Confluence-specific shapes are recognised via:

* ``confluence-page:`` / ``confluence-attachment:`` / … synthetic URIs in
  ``Link`` and ``Image`` targets → ``ConfluenceLink`` / ``ConfluenceImage``
  via :mod:`.confluence_uris`.
* ``{{confluence:name ...}}`` / ``{{confluence-raw:BASE64}}`` inline markers
  in ``Text`` tokens → ``InlineMacro`` / ``RawInline``.
* ``:::callout-<kind>`` fenced divs → ``Callout``.
* ``:::confluence-macro {…}`` fenced divs → ``ConfluenceMacro``.
* ` ```confluence-xml ` fenced code blocks → ``RawBlock(format="confluence-storage")``.

Fallback policy (spec S30 §"Fallback policy"):
  inline HTML     → ``RawInline(format="html")``
  block HTML      → ``RawBlock(format="html")``
  confluence-xml  → ``RawBlock(format="confluence-storage")``
  unknown fences  → ``CodeBlock(language=<info>)``

Topic-grouped sub-modules: ``macros``, ``inlines``, ``listing``,
``table``, ``layout``, ``blocks``. The marker regexes live one level up
in :mod:`mdd.markdown.ir._patterns`, shared with the markdown-it rule.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Literal

from mdd.ir.document import Document
from mdd.ir.identity import assign_ids
from mdd.ir.nodes import (
    Block,
    BlockQuote,
    BulletList,
    Heading,
    Inline,
    OrderedList,
    Origin,
    Paragraph,
    RawBlock,
    RawInline,
    Text,
)

from ..flavour import build_md
from .blocks import consume_block

if TYPE_CHECKING:
    from mdd.ir.fallback import IRContext

__all__ = ["parse_markdown"]

_MD = build_md()


def parse_markdown(
    md: str,
    *,
    ctx: IRContext | None = None,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> Document:
    """Parse *md* into a ``Document``.

    Args:
        md:   The markdown source string.
        ctx:  Optional mutable context; fallback events are appended to it.
        mode: ``"normalising"`` (default) or ``"preserving"``. In preserving
              mode, ``Origin`` metadata is attached to text leaves with
              ``source_format="markdown"`` and the verbatim UTF-8 bytes of the
              content as ``raw_bytes``. Structural nodes get an ``Origin`` with
              empty ``raw_bytes``.

    Returns:
        A fully identity-stamped ``Document`` with ``source_format="markdown"``.
    """
    tokens = _MD.parse(md)
    blocks: list[Block] = []
    i = 0
    while i < len(tokens):
        i = consume_block(tokens, i, blocks, ctx)

    if mode == "preserving":
        blocks = _attach_origin_to_blocks_md(blocks)

    doc = Document(children=blocks, source_format="markdown")
    result = assign_ids(doc)
    if ctx is not None:
        return _merge_fallbacks(result, ctx)
    return result


_MD_ORIGIN = Origin(source_format="markdown")


def _attach_origin_to_blocks_md(blocks: list[Block]) -> list[Block]:
    """Recursively attach Origin(source_format="markdown") to all blocks and text inlines."""
    return [_attach_origin_to_block_md(b) for b in blocks]


def _attach_origin_to_block_md(block: Block) -> Block:
    if isinstance(block, (Paragraph, Heading)):
        new_inlines = _attach_origin_to_inlines_md(block.inlines)
        return replace(block, inlines=new_inlines, origin=_MD_ORIGIN)
    if isinstance(block, (BulletList, OrderedList)):
        new_items = [
            replace(
                item,
                children=_attach_origin_to_blocks_md(item.children),
                origin=_MD_ORIGIN,
            )
            for item in block.items
        ]
        return replace(block, items=new_items, origin=_MD_ORIGIN)
    if isinstance(block, BlockQuote):
        new_children = _attach_origin_to_blocks_md(block.children)
        return replace(block, children=new_children, origin=_MD_ORIGIN)
    if isinstance(block, RawBlock):
        # `content` + the writer's RawBlock branch is sufficient — storing
        # raw_bytes would just duplicate the same string.
        return replace(block, origin=_MD_ORIGIN)
    # Structural nodes: origin with empty raw_bytes — structure-driven re-emission.
    if "origin" in getattr(type(block), "__dataclass_fields__", {}):
        return replace(block, origin=_MD_ORIGIN)  # pyright: ignore[reportCallIssue]
    return block


def _attach_origin_to_inlines_md(inlines: list[Inline]) -> list[Inline]:
    """Attach Origin to Text and RawInline tokens for preserving mode."""
    result: list[Inline] = []
    for tok in inlines:
        if isinstance(tok, (Text, RawInline)):
            # raw_bytes is redundant with content for these tokens — skip.
            origin = Origin(source_format="markdown")
            result.append(replace(tok, origin=origin))
        else:
            result.append(tok)
    return result


def _merge_fallbacks(doc: Document, ctx: IRContext) -> Document:
    return replace(doc, fallbacks=list(ctx.fallbacks))
