"""Inline-macro splitting: text → ``InlineMacro`` / ``RawInline``."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from mdd.ir.fallback import emit_inline_fallback
from mdd.ir.nodes import Inline, InlineMacro, Text

from .._patterns import ATTR_RE, INLINE_MACRO_RE, INLINE_RAW_RE

if TYPE_CHECKING:
    import re

    from mdd.ir.fallback import IRContext


def split_inline_macros(tokens: list[Inline], ctx: IRContext | None) -> list[Inline]:
    out: list[Inline] = []
    for tok in tokens:
        if isinstance(tok, Text):
            out.extend(_split_text(tok.content, ctx))
        else:
            out.append(tok)
    return out


def _inline_macro_from_match(m: re.Match[str]) -> InlineMacro:
    """Build an ``InlineMacro`` from a ``{{confluence:name k="v"}}`` match."""
    attrs_str = m.group(2) or ""
    params: dict[str, str] = {
        m2.group(1): m2.group(2).replace('\\"', '"').replace("\\\\", "\\")
        for m2 in ATTR_RE.finditer(attrs_str)
    }
    return InlineMacro(name=m.group(1), params=params)


def _raw_inline_from_match(
    m: re.Match[str], ctx: IRContext | None, *, full_content_on_decode_error: str | None = None
) -> Inline:
    """Decode a ``{{confluence-raw:BASE64}}`` match into a ``RawInline`` fallback.

    When the base64 payload fails to decode, fall back to *full_content_on_decode_error*
    (caller-supplied verbatim source) when given, else to the matched text.
    """
    try:
        raw_xml = base64.b64decode(m.group(1)).decode("utf-8")
    except Exception:
        raw_xml = (
            full_content_on_decode_error if full_content_on_decode_error is not None else m.group(0)
        )
    return emit_inline_fallback(
        raw_xml,
        source_format="html",
        reason="confluence-raw base64 marker",
        ctx=ctx,
        format_override="html",
    )


def _split_text(text: str, ctx: IRContext | None) -> list[Inline]:
    out: list[Inline] = []
    candidates: list[tuple[int, int, str, re.Match[str]]] = [
        *((m.start(), m.end(), "macro", m) for m in INLINE_MACRO_RE.finditer(text)),
        *((m.start(), m.end(), "raw", m) for m in INLINE_RAW_RE.finditer(text)),
    ]
    candidates.sort(key=lambda x: x[0])

    pos = 0
    for start, end, kind, m in candidates:
        if start < pos:
            continue
        if start > pos:
            out.append(Text(text[pos:start]))
        if kind == "macro":
            out.append(_inline_macro_from_match(m))
        else:
            out.append(_raw_inline_from_match(m, ctx))
        pos = end
    if pos < len(text):
        out.append(Text(text[pos:]))
    return out


def parse_confluence_inline_marker(content: str, ctx: IRContext | None) -> list[Inline]:
    """Parse a ``confluence_inline`` token content into IR inline(s)."""
    m = INLINE_MACRO_RE.match(content)
    if m:
        return [_inline_macro_from_match(m)]

    m2 = INLINE_RAW_RE.match(content)
    if m2:
        return [_raw_inline_from_match(m2, ctx, full_content_on_decode_error=content)]

    return [Text(content)]
