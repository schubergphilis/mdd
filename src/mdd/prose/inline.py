"""Inline span masking for a single line of prose.

A masked span is passed through byte-for-byte by every fixer. A check may
*read* one — ``anchors`` must read link targets, ``lint``'s literal escape must
recognise an ``inline-code`` span — but no check may rewrite one.

Masking runs per line rather than per document because every construct here is
inline and CommonMark does not let a code span or a link straddle a blank line;
a multi-line construct is a block and is the block classifier's business.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_PUNCTUATION = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

_HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(\s[^<>]*)?/?>")
_AUTOLINK = re.compile(r"<[A-Za-z][A-Za-z0-9+.-]*:[^<>\s]*>|<[^<>\s@]+@[^<>\s@]+\.[^<>\s@]+>")


class SpanClass(StrEnum):
    """What a masked span is."""

    INLINE_CODE = "inline-code"
    LINK = "link"
    AUTOLINK = "autolink"
    RAW_HTML = "raw-html"
    FOOTNOTE_REF = "footnote-ref"
    MATH = "math"
    ESCAPE = "escape"


@dataclass(frozen=True)
class Span:
    """A half-open ``[start, end)`` byte range on one line, and what it is."""

    start: int
    end: int
    cls: SpanClass


@dataclass(frozen=True)
class LinkRef:
    """A link target found on a line, with the 0-based column it starts at."""

    start: int
    target: str


@dataclass(frozen=True)
class InlineScan:
    """The masks and link targets found on one line."""

    masks: tuple[Span, ...]
    links: tuple[LinkRef, ...]


def _scan_code_span(text: str, i: int) -> int:
    """Return the end offset of a code span opening at *i*, or ``i`` if unclosed."""
    n = 0
    while i + n < len(text) and text[i + n] == "`":
        n += 1
    closer = "`" * n
    probe = i + n
    while True:
        found = text.find(closer, probe)
        if found == -1:
            return i
        run_end = found + n
        if run_end < len(text) and text[run_end] == "`":
            probe = run_end
            while probe < len(text) and text[probe] == "`":
                probe += 1
            continue
        return run_end


def _match_bracket(text: str, i: int) -> int:
    """Return the offset just past the ``]`` closing a ``[`` at *i*, or ``i``."""
    depth = 0
    pos = i
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == "`":
            pos = max(_scan_code_span(text, pos), pos + 1)
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return i


def _match_paren(text: str, i: int) -> int:
    """Return the offset just past the ``)`` closing a ``(`` at *i*, or ``i``."""
    depth = 0
    pos = i
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return i


def parse_link_target(inline: str) -> str:
    """Extract the destination from a link's ``(...)`` interior."""
    body = inline.strip()
    if body.startswith("<"):
        end = body.find(">")
        if end != -1:
            return body[1:end]
    return body.split()[0] if body.split() else ""


def _scan_bracketed(text: str, i: int, out: list[Span], links: list[LinkRef]) -> int:
    """Handle a construct starting at ``[`` or ``![``; return the next offset."""
    open_at = i + 1 if text[i] == "!" else i
    if text.startswith("[^", open_at):
        end = _match_bracket(text, open_at)
        if end > open_at:
            out.append(Span(i, end, SpanClass.FOOTNOTE_REF))
            return end
        return i + 1
    text_end = _match_bracket(text, open_at)
    if text_end == open_at:
        return i + 1
    if text_end < len(text) and text[text_end] == "(":
        paren_end = _match_paren(text, text_end)
        if paren_end > text_end:
            out.append(Span(i, paren_end, SpanClass.LINK))
            links.append(
                LinkRef(text_end + 1, parse_link_target(text[text_end + 1 : paren_end - 1]))
            )
            return paren_end
    if text_end < len(text) and text[text_end] == "[":
        ref_end = _match_bracket(text, text_end)
        if ref_end > text_end:
            out.append(Span(i, ref_end, SpanClass.LINK))
            return ref_end
    return i + 1


def _scan_angle(text: str, i: int, out: list[Span]) -> int:
    """Handle a construct starting at ``<``; return the next offset."""
    autolink = _AUTOLINK.match(text, i)
    if autolink is not None:
        out.append(Span(i, autolink.end(), SpanClass.AUTOLINK))
        return autolink.end()
    tag = _HTML_TAG.match(text, i)
    if tag is not None:
        out.append(Span(i, tag.end(), SpanClass.RAW_HTML))
        return tag.end()
    return i + 1


def _scan_math(text: str, i: int, out: list[Span]) -> int:
    """Handle a ``$…$`` inline math span; return the next offset."""
    if i + 1 >= len(text) or text[i + 1].isspace():
        return i + 1
    end = text.find("$", i + 1)
    if end == -1:
        return i + 1
    out.append(Span(i, end + 1, SpanClass.MATH))
    return end + 1


def _scan_backticks(text: str, i: int, out: list[Span]) -> int:
    """Mask a code span opening at *i*, or skip its whole run; return the next offset.

    Skipping the *whole* run matters: restarting one character in let a shorter
    sub-run close against the opening backtick of the next genuine code span,
    leaving that span unmasked and open to a rewrite.
    """
    end = _scan_code_span(text, i)
    if end != i:
        out.append(Span(i, end, SpanClass.INLINE_CODE))
        return end
    while i < len(text) and text[i] == "`":
        i += 1
    return i


def scan(text: str, *, start: int = 0) -> InlineScan:
    """Mask every inline construct in ``text[start:]`` and collect link targets.

    Offsets in the result are absolute within *text*, so a caller that passed a
    block prefix in *start* still gets columns it can report directly.
    """
    masks: list[Span] = []
    links: list[LinkRef] = []
    i = start
    while i < len(text):
        char = text[i]
        if char == "\\" and i + 1 < len(text) and text[i + 1] in _PUNCTUATION:
            masks.append(Span(i, i + 2, SpanClass.ESCAPE))
            i += 2
        elif char == "`":
            i = _scan_backticks(text, i, masks)
        elif char == "[" or (char == "!" and text.startswith("[", i + 1)):
            i = _scan_bracketed(text, i, masks, links)
        elif char == "<":
            i = _scan_angle(text, i, masks)
        elif char == "$":
            i = _scan_math(text, i, masks)
        else:
            i += 1
    return InlineScan(masks=tuple(masks), links=tuple(links))


def mask_flags(length: int, masks: tuple[Span, ...]) -> list[bool]:
    """Return a per-character "is masked" vector of *length* for *masks*."""
    flags = [False] * length
    for span in masks:
        for index in range(max(0, span.start), min(length, span.end)):
            flags[index] = True
    return flags


def span_at(masks: tuple[Span, ...], column: int) -> Span | None:
    """Return the mask covering *column*, or ``None``."""
    return next((s for s in masks if s.start <= column < s.end), None)
