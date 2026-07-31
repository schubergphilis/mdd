"""Inline consumption: markdown-it tokens → IR ``Inline`` nodes."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from mdd.ir.fallback import emit_inline_fallback
from mdd.ir.nodes import (
    Code,
    Emph,
    Image,
    Inline,
    LineBreak,
    Link,
    RawInline,
    SoftBreak,
    Strikethrough,
    Strong,
    Text,
)

from ..confluence_uris import parse_confluence_image_uri, parse_confluence_link_uri
from .macros import parse_confluence_inline_marker

if TYPE_CHECKING:
    from collections.abc import Callable

    from markdown_it.token import Token

    from mdd.ir.fallback import IRContext


def consume_inlines(inline_tok: Token, ctx: IRContext | None) -> list[Inline]:
    children: list[Any] = list(inline_tok.children or [])
    out: list[Inline] = []
    _consume_inline_seq(children, 0, len(children), out, ctx)
    return _merge_inline_raw_html_pairs(out)


_HTML_OPEN_TAG_RE = re.compile(r"^<([A-Za-z][A-Za-z0-9-]*)(\s[^>]*)?>$")
_HTML_CLOSE_TAG_RE = re.compile(r"^</([A-Za-z][A-Za-z0-9-]*)\s*>$")


def _merge_inline_raw_html_pairs(tokens: list[Inline]) -> list[Inline]:
    """Merge ``RawInline(<tag>) + Text(...) + RawInline(</tag>)`` runs.

    markdown-it-py emits inline raw HTML as three separate tokens
    (``html_inline`` for the open tag, ``text`` for the content,
    ``html_inline`` for the close tag). The Confluence storage reader
    keeps the same shape as a single ``RawInline`` because lxml parses
    `<samp>shell output</samp>` as one element. Merging here makes the
    two readers produce structurally identical IR and keeps ``reattach``
    index-aligned across the markdown round-trip (fixture 1212604).
    """
    merged: list[Inline] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if (
            isinstance(tok, RawInline)
            and tok.format == "html"
            and i + 2 < len(tokens)
            and isinstance(tokens[i + 1], Text)
            and isinstance(tokens[i + 2], RawInline)
        ):
            open_m = _HTML_OPEN_TAG_RE.match(tok.content)
            next_raw = tokens[i + 2]
            assert isinstance(next_raw, RawInline)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
            close_m = (
                _HTML_CLOSE_TAG_RE.match(next_raw.content) if next_raw.format == "html" else None
            )
            if open_m and close_m and open_m.group(1).lower() == close_m.group(1).lower():
                inner_text = tokens[i + 1]
                assert isinstance(inner_text, Text)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
                merged.append(
                    RawInline(
                        content=f"{tok.content}{inner_text.content}{next_raw.content}",
                        format="html",
                    )
                )
                i += 3
                continue
        merged.append(tok)
        i += 1
    return merged


# Simple "consume one token, emit one inline" handlers — by token type to
# IR factory. The token's `content` is the only input; no index lookahead
# and no recursion needed.
_SIMPLE_INLINE_BUILDERS: dict[str, Callable[[str], Inline]] = {
    "text": Text,
    "softbreak": lambda _c: SoftBreak(),
    "hardbreak": lambda _c: LineBreak(),
    "code_inline": lambda c: Code(content=c),
}

# Wrapper tokens: `<kind>_open` … `<kind>_close` with inner tokens that
# need recursive consumption. Mapped to (close_type, wrapper_factory).
_WRAPPER_INLINES: dict[str, tuple[str, Callable[[list[Inline]], Inline]]] = {
    "strong_open": ("strong_close", lambda inner: Strong(tokens=inner)),
    "em_open": ("em_close", lambda inner: Emph(tokens=inner)),
    "s_open": ("s_close", lambda inner: Strikethrough(tokens=inner)),
}


def _consume_inline_seq(
    tokens: list[Token],
    start: int,
    end: int,
    out: list[Inline],
    ctx: IRContext | None,
) -> None:
    i = start
    while i < end:
        tok = tokens[i]
        t = tok.type

        simple = _SIMPLE_INLINE_BUILDERS.get(t)
        if simple is not None:
            out.append(simple(tok.content))
            i += 1
            continue

        wrapper = _WRAPPER_INLINES.get(t)
        if wrapper is not None:
            close_type, factory = wrapper
            j = _find_match(tokens, i, close_type, end)
            inner: list[Inline] = []
            _consume_inline_seq(tokens, i + 1, j, inner, ctx)
            out.append(factory(inner))
            i = j + 1
            continue

        if t == "link_open":
            i = _consume_link(tokens, i, end, out, ctx)
            continue
        if t == "image":
            out.append(_image_from_token(tok))
            i += 1
            continue
        if t == "html_inline":
            out.append(
                emit_inline_fallback(
                    tok.content,
                    source_format="html",
                    reason="html_inline token",
                    ctx=ctx,
                    format_override="html",
                )
            )
            i += 1
            continue
        if t == "confluence_inline":
            out.extend(parse_confluence_inline_marker(tok.content, ctx))
            i += 1
            continue
        i += 1


def _consume_link(
    tokens: list[Token], i: int, end: int, out: list[Inline], ctx: IRContext | None
) -> int:
    tok = tokens[i]
    j = _find_match(tokens, i, "link_close", end)
    href = str(tok.attrGet("href") or "")
    title_raw = tok.attrGet("title")
    title_str = str(title_raw) if title_raw is not None else None
    inner: list[Inline] = []
    _consume_inline_seq(tokens, i + 1, j, inner, ctx)
    out.append(_build_link(href, title_str, inner))
    return j + 1


def _image_from_token(tok: Token) -> Inline:
    src = str(tok.attrGet("src") or "")
    alt = str(tok.attrGet("alt") or tok.content)
    title_raw = tok.attrGet("title")
    title = str(title_raw) if title_raw is not None else None
    return _build_image(src, alt, title)


def _find_match(tokens: list[Token], i: int, close_type: str, end: int) -> int:
    depth = 0
    open_type = tokens[i].type
    j = i + 1
    while j < end:
        if tokens[j].type == open_type:
            depth += 1
        elif tokens[j].type == close_type:
            if depth == 0:
                return j
            depth -= 1
        j += 1
    return end


def _build_link(href: str, title: str | None, body: list[Inline]) -> Inline:
    # Try the confluence-* schemes on the raw, still-encoded href first:
    # they use percent-encoding as their own internal escaping (e.g. a
    # slash in a page title round-trips as %2F), and unquoting the whole
    # href up front — as the plain-Link fallback below does for
    # readability — would strip that escaping before it can be read back.
    conf = parse_confluence_link_uri(href)
    if conf is not None:
        return replace(conf, body_tokens=body)
    decoded = urllib.parse.unquote(href)
    return Link(href=decoded, tokens=body, title=title)


def _build_image(src: str, alt: str, title: str | None) -> Inline:
    conf = parse_confluence_image_uri(src)
    if conf is not None:
        # Merge width/align/alt from title slot ("width=400 align=center").
        attributes = dict(conf.attributes)
        if title:
            for pair in title.split():
                if "=" in pair:
                    k, _, v = pair.partition("=")
                    attributes[f"ac:{k}"] = v
        if alt:
            attributes["ac:alt"] = alt
        return replace(conf, attributes=attributes)
    decoded = urllib.parse.unquote(src)
    return Image(src=decoded, alt=alt, title=title)
