"""Confluence storage XHTML → IR entry point.

Wraps the fragment in a synthetic root with the ``ac:`` / ``ri:``
namespace declarations so a single parser pass works.  HTML5 entities
(``&hellip;``, ``&rsquo;``, ``&nbsp;``, ...) are substituted to their
Unicode characters before parsing because lxml silently drops unknown
entities.

See spec S29 for the full element coverage table and fallback policy.
"""

from __future__ import annotations

import html.entities
import re
import warnings
from dataclasses import replace
from typing import Literal

from lxml import etree

from mdd.ir.document import Document
from mdd.ir.fallback import IRContext
from mdd.ir.identity import assign_ids
from mdd.ir.nodes import (
    Block,
    BlockQuote,
    BulletList,
    Callout,
    Code,
    ConfluenceImage,
    ConfluenceLink,
    ConfluenceMacro,
    Emph,
    Heading,
    Image,
    Inline,
    InlineMacro,
    Layout,
    Link,
    OrderedList,
    Origin,
    Paragraph,
    RawBlock,
    RawInline,
    Strikethrough,
    Strong,
    Table,
    Text,
)

from .elements import read_blocks_from_container

_AC = "http://atlassian.com/content"
_RI = "http://atlassian.com/repository/confluence/1.0"

_XML_PREDEFINED_ENTITIES = frozenset({"amp", "lt", "gt", "quot", "apos"})
_ENTITY_REF = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")


_PUA_START = 0xE000  # Unicode Private Use Area start
_PUA_END = 0xF8FF  # PUA end — gives ~6,400 slots, far more than any real page needs

_XML_PREDEFINED_CHARS: dict[str, str] = {
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "apos": "'",
}


def _resolve_entity_char(name: str) -> str | None:
    """Map an HTML/XML entity name to its decoded character, or ``None`` for
    unknown names. Handles both XML-predefined entities (``amp``/``lt``/
    ``gt``/``quot``/``apos``) and the full HTML5 named-entity table."""
    if name in _XML_PREDEFINED_CHARS:
        return _XML_PREDEFINED_CHARS[name]
    return html.entities.html5.get(name + ";")


class _PuaAllocator:
    """Allocate Unicode PUA codepoints in order. Each allocation records the
    original entity string so the writer can later restore it verbatim."""

    def __init__(self) -> None:
        self.next_codepoint = _PUA_START
        self.mapping: dict[str, str] = {}

    def allocate(self, entity_str: str) -> str:
        if self.next_codepoint > _PUA_END:
            raise ValueError(
                f"too many entity references in source "
                f"({self.next_codepoint - _PUA_START}); "
                "preserving-mode PUA budget exhausted"
            )
        pua = chr(self.next_codepoint)
        self.next_codepoint += 1
        self.mapping[pua] = entity_str
        return pua


def _substitute_one_entity(
    xhtml: str,
    i: int,
    *,
    in_tag: bool,
    allocator: _PuaAllocator,
) -> tuple[str, int] | None:
    """Try to substitute the entity reference starting at ``xhtml[i]``.

    Returns ``(replacement, new_index)`` on a match — where ``replacement``
    is either the original ``&entity;`` string (preserved when the entity
    is one of the five XML-predefined entities *inside* an open tag, so
    lxml's attribute parser can decode it natively, or when the entity
    name is unknown and we pass it through) or a freshly-allocated PUA
    marker character. Returns ``None`` when no entity matches and the
    caller should advance one character.
    """
    m = _ENTITY_REF.match(xhtml, i)
    if m is None:
        return None
    name = m.group(1)
    entity_str = m.group(0)
    # Inside tags, XML-predefined entities pass through so lxml's attribute
    # parser handles them natively. HTML5-only entities inside attribute
    # values still need PUA substitution (lxml would silently drop them
    # under ``recover=True``; issue #90).
    if in_tag and name in _XML_PREDEFINED_ENTITIES:
        return entity_str, m.end()
    char = _resolve_entity_char(name)
    if char is None:
        # Unknown entity name — pass through verbatim.
        return entity_str, m.end()
    return allocator.allocate(entity_str), m.end()


def _substitute_entities_with_pua_markers(
    xhtml: str,
) -> tuple[str, dict[str, str]]:
    """Substitute every HTML5 entity reference (and XML-predefined entities in
    element text) with a unique Unicode Private Use Area marker char.

    Returns ``(substituted_text, pua_to_entity)`` where ``pua_to_entity[chr]``
    is the original entity string (e.g. ``"&hellip;"``, ``"&quot;"``). The
    substituted text round-trips through lxml without entity decoding because
    PUA chars are plain Unicode codepoints; afterwards each ``Text`` node's
    content can be walked locally to recover ``entity_form``.

    Inside tags (attribute values like ``ri:content-title="X&rsquo;s thing"``),
    the five XML-predefined entities (``amp``/``lt``/``gt``/``quot``/``apos``)
    pass through unchanged so lxml decodes them natively during attribute
    parsing. HTML5-only entities (``rsquo``, ``mdash``, ``hellip``, ``nbsp``,
    …) inside attribute values are *also* substituted to PUA markers so the
    character survives; lxml would otherwise raise ``ERR_UNDECLARED_ENTITY``
    and silently drop the reference under ``recover=True`` (issue #90). The
    PUA codepoint becomes part of the attribute value as a plain Unicode
    character, then ``_reentity_pua`` restores it on the way out.
    Attribute-level ``entity_form`` is intentionally *not* recorded — we
    accept that round-trip loss; preserving the character is what matters.
    """
    allocator = _PuaAllocator()
    out: list[str] = []
    i = 0
    n = len(xhtml)
    in_tag = False
    while i < n:
        c = xhtml[i]
        if c == "<":
            in_tag = True
            out.append(c)
            i += 1
            continue
        if c == ">":
            in_tag = False
            out.append(c)
            i += 1
            continue
        if c == "&":
            replaced = _substitute_one_entity(xhtml, i, in_tag=in_tag, allocator=allocator)
            if replaced is not None:
                out.append(replaced[0])
                i = replaced[1]
                continue
        out.append(c)
        i += 1
    return "".join(out), allocator.mapping


def _reentity_pua(content: str, pua_to_entity: dict[str, str]) -> str:
    """Replace every PUA marker in ``content`` with its original entity string.

    Used for fields where the writer emits the value verbatim and can't
    consult ``entity_form`` (e.g. ``ConfluenceMacro.params`` values that
    contain JSON-style ``&quot;`` runs — fixture 1114411). Restores the
    source bytes directly rather than going through the
    decode-then-resubstitute dance Text/Code use.
    """
    if not pua_to_entity:
        return content
    parts: list[str] = []
    for c in content:
        ent = pua_to_entity.get(c)
        parts.append(ent if ent is not None else c)
    return "".join(parts)


def _decode_pua_to_chars(content: str, pua_to_entity: dict[str, str]) -> str:
    """Replace every PUA marker in ``content`` with its decoded Unicode
    character (e.g. PUA(``&rsquo;``) → ``'``).

    Used for XML attribute values, where we deliberately drop the original
    entity form (per the design comment on
    :func:`_substitute_entities_with_pua_markers`) and only need the
    character to survive. Unknown entity names keep the PUA char so the
    bug is visible rather than silently dropped.
    """
    if not pua_to_entity:
        return content
    parts: list[str] = []
    for c in content:
        entity_str = pua_to_entity.get(c)
        if entity_str is None:
            parts.append(c)
            continue
        name = entity_str[1:-1]  # strip & and ;
        if name in _XML_PREDEFINED_ENTITIES:
            parts.append({"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}[name])
        else:
            parts.append(html.entities.html5.get(name + ";", c))
    return "".join(parts)


def _decode_pua_in_text(content: str, pua_to_entity: dict[str, str]) -> tuple[str, dict[int, str]]:
    """Walk a Text content string, replace PUA markers with their decoded chars,
    and record ``{offset: entity_str}`` for each replacement.

    Multi-codepoint decodings (rare for HTML5) shift subsequent offsets by
    the decoded length; the offset stored points to the start of the decoded
    run, matching the writer's substitution loop.
    """
    if not pua_to_entity:
        return content, {}
    new_chars: list[str] = []
    entity_form: dict[int, str] = {}
    for c in content:
        entity_str = pua_to_entity.get(c)
        if entity_str is None:
            new_chars.append(c)
            continue
        name = entity_str[1:-1]  # strip & and ;
        if name in _XML_PREDEFINED_ENTITIES:
            decoded = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}[name]
        else:
            decoded = html.entities.html5.get(name + ";", c)
        entity_form[len(new_chars)] = entity_str
        new_chars.append(decoded)
    return "".join(new_chars), entity_form


_STORAGE_ORIGIN = Origin(source_format="confluence-storage")


def _attach_origin_paragraph_like(
    block: Paragraph | Heading, pua_to_entity: dict[str, str]
) -> Block:
    """Paragraph / Heading: recurse into inlines, attach a bare origin."""
    new_inlines = _attach_origin_to_inlines(block.inlines, pua_to_entity)
    return replace(block, inlines=new_inlines, origin=_STORAGE_ORIGIN)


def _attach_origin_list(block: BulletList | OrderedList, pua_to_entity: dict[str, str]) -> Block:
    """BulletList / OrderedList: recurse into each item's children."""
    new_items = [
        replace(item, children=_attach_origin_to_blocks(item.children, pua_to_entity))
        for item in block.items
    ]
    return replace(block, items=new_items, origin=_STORAGE_ORIGIN)


def _attach_origin_blockquote(block: BlockQuote, pua_to_entity: dict[str, str]) -> Block:
    """BlockQuote: recurse into children, attach origin."""
    return replace(
        block,
        children=_attach_origin_to_blocks(block.children, pua_to_entity),
        origin=_STORAGE_ORIGIN,
    )


def _attach_origin_macro(block: Callout | ConfluenceMacro, pua_to_entity: dict[str, str]) -> Block:
    """Callout / ConfluenceMacro: re-substitute PUA markers in params (and
    Callout title) back to ``&entity;`` form because the writer emits these
    fields verbatim, then recurse into the body. Param values must round-
    trip even when they carry raw markup (fixture 164069)."""
    new_params = {k: _reentity_pua(v, pua_to_entity) for k, v in block.params.items()}
    new_body = _attach_origin_to_blocks(block.body, pua_to_entity)
    if isinstance(block, Callout):
        new_title = _reentity_pua(block.title, pua_to_entity) if block.title is not None else None
        return replace(
            block, body=new_body, params=new_params, title=new_title, origin=_STORAGE_ORIGIN
        )
    return replace(block, body=new_body, params=new_params, origin=_STORAGE_ORIGIN)


def _attach_origin_table(block: Table, pua_to_entity: dict[str, str]) -> Block:
    """Table: recurse into every cell of every row."""
    new_rows = [
        replace(
            row,
            cells=[
                replace(cell, children=_attach_origin_to_blocks(cell.children, pua_to_entity))
                for cell in row.cells
            ],
        )
        for row in block.rows
    ]
    return replace(block, rows=new_rows, origin=_STORAGE_ORIGIN)


def _attach_origin_layout(block: Layout, pua_to_entity: dict[str, str]) -> Block:
    """Layout: recurse into every cell of every section."""
    new_sections = [
        replace(
            section,
            cells=[
                replace(cell, children=_attach_origin_to_blocks(cell.children, pua_to_entity))
                for cell in section.cells
            ],
        )
        for section in block.sections
    ]
    return replace(block, sections=new_sections, origin=_STORAGE_ORIGIN)


def _attach_origin_raw(block: RawBlock, pua_to_entity: dict[str, str]) -> Block:
    """RawBlock: strip PUA markers from ``content``; record ``entity_form``
    so the writer re-emits the original entities verbatim. Uses
    ``content`` + ``entity_form`` rather than ``raw_bytes`` because the
    writer's RawBlock branch consults the former; raw_bytes would just
    duplicate the content."""
    new_content, entity_form = _decode_pua_in_text(block.content, pua_to_entity)
    origin = Origin(source_format="confluence-storage", entity_form=entity_form)
    return replace(block, content=new_content, origin=origin)


def _attach_origin_generic(block: Block, pua_to_entity: dict[str, str]) -> Block:
    """Catch-all for blocks that own an ``origin`` field but no specific
    handler (CodeBlock, HorizontalRule, etc.). When the block has a
    ``content: str`` field, PUA markers there get decoded as for RawBlock;
    otherwise just attach a bare origin. Blocks without an ``origin``
    field pass through untouched."""
    block_fields = getattr(type(block), "__dataclass_fields__", {})
    if "origin" not in block_fields:
        return block
    if hasattr(block, "content") and isinstance(getattr(block, "content"), str):  # noqa: B009
        new_content, entity_form = _decode_pua_in_text(
            getattr(block, "content"),  # noqa: B009
            pua_to_entity,
        )
        origin = Origin(source_format="confluence-storage", entity_form=entity_form)
        return replace(block, content=new_content, origin=origin)  # pyright: ignore[reportCallIssue]
    return replace(block, origin=_STORAGE_ORIGIN)  # pyright: ignore[reportCallIssue]


def _attach_origin_to_block(block: Block, pua_to_entity: dict[str, str]) -> Block:
    """Dispatch one block to its origin-attaching handler. Block-type ->
    handler routing lives here in one place; new IR block types only need
    a new handler + a new dispatch arm."""
    # Ordered isinstance dispatch: each pair is (type-or-tuple, handler).
    # Order doesn't matter here because the union arms are disjoint at the
    # type level, but keeping it close to the original branch order makes
    # diff review easier.
    if isinstance(block, (Paragraph, Heading)):
        return _attach_origin_paragraph_like(block, pua_to_entity)
    if isinstance(block, (BulletList, OrderedList)):
        return _attach_origin_list(block, pua_to_entity)
    if isinstance(block, (Callout, ConfluenceMacro)):
        return _attach_origin_macro(block, pua_to_entity)
    if isinstance(block, BlockQuote):
        return _attach_origin_blockquote(block, pua_to_entity)
    return _attach_origin_structural_or_generic(block, pua_to_entity)


def _attach_origin_structural_or_generic(block: Block, pua_to_entity: dict[str, str]) -> Block:
    """Second-tier dispatch for the structural and catch-all cases."""
    if isinstance(block, Table):
        return _attach_origin_table(block, pua_to_entity)
    if isinstance(block, Layout):
        return _attach_origin_layout(block, pua_to_entity)
    if isinstance(block, RawBlock):
        return _attach_origin_raw(block, pua_to_entity)
    return _attach_origin_generic(block, pua_to_entity)


def _attach_origin_to_blocks(
    blocks: list[Block],
    pua_to_entity: dict[str, str],
) -> list[Block]:
    """Walk blocks and decode PUA-entity markers in Text leaves, attaching
    an ``Origin`` carrying the recovered ``entity_form`` so the writer can
    re-substitute the original entities on emit.

    Structural nodes (Paragraph, Heading, list / table / layout containers,
    ...) recurse into their children; the structural node itself gets a
    bare ``Origin(source_format="confluence-storage")``.
    """
    return [_attach_origin_to_block(block, pua_to_entity) for block in blocks]


def _decode_attrs(attrs: dict[str, str], pua_to_entity: dict[str, str]) -> dict[str, str]:
    return {k: _decode_pua_to_chars(v, pua_to_entity) for k, v in attrs.items()}


def _decode_optional(value: str | None, pua_to_entity: dict[str, str]) -> str | None:
    return None if value is None else _decode_pua_to_chars(value, pua_to_entity)


def _decode_text_like(tok: Inline, pua_to_entity: dict[str, str]) -> Inline:
    """Handle Text / Code / RawInline content decoding."""
    if isinstance(tok, (Text, Code)):
        new_content, entity_form = _decode_pua_in_text(tok.content, pua_to_entity)
        # raw_bytes intentionally empty for Text / Code — the writer
        # consults `content` + `entity_form` directly; storing the UTF-8
        # encoding here would just double the sidecar size (spec S31
        # open question 1).
        origin = Origin(source_format="confluence-storage", entity_form=entity_form)
        return replace(tok, content=new_content, origin=origin)
    assert isinstance(tok, RawInline)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    new_content, _ = _decode_pua_in_text(tok.content, pua_to_entity)
    return replace(tok, content=new_content)


def _decode_link_like(tok: Inline, pua_to_entity: dict[str, str]) -> Inline:
    """Handle Link / Image / ConfluenceLink / ConfluenceImage attribute decoding."""
    if isinstance(tok, Link):
        return replace(
            tok,
            href=_decode_pua_to_chars(tok.href, pua_to_entity),
            title=_decode_optional(tok.title, pua_to_entity),
            tokens=_attach_origin_to_inlines(tok.tokens, pua_to_entity),
            attributes=_decode_attrs(tok.attributes, pua_to_entity),
        )
    if isinstance(tok, Image):
        return replace(
            tok,
            src=_decode_pua_to_chars(tok.src, pua_to_entity),
            alt=_decode_pua_to_chars(tok.alt, pua_to_entity),
            title=_decode_optional(tok.title, pua_to_entity),
            attributes=_decode_attrs(tok.attributes, pua_to_entity),
        )
    if isinstance(tok, ConfluenceLink):
        return replace(
            tok,
            target=_decode_pua_to_chars(tok.target, pua_to_entity),
            space_key=_decode_pua_to_chars(tok.space_key, pua_to_entity),
            version_at_save=_decode_pua_to_chars(tok.version_at_save, pua_to_entity),
            posting_day=_decode_pua_to_chars(tok.posting_day, pua_to_entity),
            page_title=_decode_pua_to_chars(tok.page_title, pua_to_entity),
            page_space_key=_decode_pua_to_chars(tok.page_space_key, pua_to_entity),
            user_local_id=_decode_pua_to_chars(tok.user_local_id, pua_to_entity),
            body_tokens=_attach_origin_to_inlines(tok.body_tokens, pua_to_entity),
            attributes=_decode_attrs(tok.attributes, pua_to_entity),
        )
    assert isinstance(tok, ConfluenceImage)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    return replace(
        tok,
        source=_decode_pua_to_chars(tok.source, pua_to_entity),
        attachment_version=_decode_optional(tok.attachment_version, pua_to_entity),
        attributes=_decode_attrs(tok.attributes, pua_to_entity),
    )


def _attach_origin_to_inlines(
    inlines: list[Inline],
    pua_to_entity: dict[str, str],
) -> list[Inline]:
    """Decode PUA markers in inline Text / RawInline, recording entity_form.

    Attribute-bearing nodes (``ConfluenceLink``, ``ConfluenceImage``,
    ``Link``, ``Image``) also have their attribute string fields decoded —
    not back to ``&entity;`` form (per the design comment on
    :func:`_substitute_entities_with_pua_markers`) but to the Unicode
    character so the value is usable downstream. issue #90.
    """
    result: list[Inline] = []
    for tok in inlines:
        if isinstance(tok, (Text, Code, RawInline)):
            result.append(_decode_text_like(tok, pua_to_entity))
        elif isinstance(tok, (Strong, Emph, Strikethrough)):
            result.append(replace(tok, tokens=_attach_origin_to_inlines(tok.tokens, pua_to_entity)))
        elif isinstance(tok, (Link, Image, ConfluenceLink, ConfluenceImage)):
            result.append(_decode_link_like(tok, pua_to_entity))
        elif isinstance(tok, InlineMacro):
            new_params = {k: _reentity_pua(v, pua_to_entity) for k, v in tok.params.items()}
            result.append(
                replace(
                    tok,
                    params=new_params,
                    attributes=_decode_attrs(tok.attributes, pua_to_entity),
                )
            )
        else:
            result.append(tok)
    return result


def parse_confluence_storage(
    storage: str,
    *,
    ctx: IRContext | None = None,
    page_title: str | None = None,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> Document:
    """Parse a Confluence storage XHTML fragment to an IR ``Document``.

    ``ctx`` receives ``FallbackEmitted`` events for every element that
    fell back to ``RawBlock`` / ``RawInline``.  Pass ``None`` (the
    default) if you don't need the event log.

    ``mode`` controls whether ``Origin`` metadata is captured on each node:

    - ``"normalising"`` (default): ``origin = None`` on every node.
    - ``"preserving"``: ``Origin`` is populated with the source byte slice
      and entity form for text leaves; structural nodes get ``Origin`` with
      ``source_format`` set but empty ``raw_bytes``.

    ``Document.source_format`` is set to ``"confluence-storage"``.
    ``Document.fallbacks`` is populated from ``ctx.fallbacks`` before
    returning.
    """
    if ctx is None:
        ctx = IRContext()

    parser = etree.XMLParser(recover=True, remove_comments=False)

    # Always go through the PUA-marker entity capture so that the writer can
    # re-emit named entities (`&mdash;`, `&hellip;`, `&quot;`, …) in either
    # mode. lxml unconditionally decodes them to their Unicode codepoints
    # during parse, and `_attach_origin_to_blocks` is the cheap part of
    # Origin (entity_form only — no raw_bytes capture); see spec S31 for
    # why we draw the preserving vs normalising line at raw_bytes rather
    # than at entity_form.
    text, pua_to_entity = _substitute_entities_with_pua_markers(storage)

    wrapped = f'<root xmlns:ac="{_AC}" xmlns:ri="{_RI}">{text}</root>'
    root = etree.fromstring(wrapped.encode("utf-8"), parser=parser)

    if parser.error_log:
        messages = "; ".join(str(e) for e in parser.error_log)
        warnings.warn(
            f"confluence.ir.reader: malformed XHTML recovered: {messages}",
            stacklevel=2,
        )

    blocks = read_blocks_from_container(root, ctx)

    blocks = _attach_origin_to_blocks(blocks, pua_to_entity)

    doc = Document(
        children=blocks,
        page_title=page_title,
        source_format="confluence-storage",
        fallbacks=list(ctx.fallbacks),
    )
    return assign_ids(doc)
