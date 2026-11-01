"""Line primitives: block-quote markers, indent columns and list-marker prefixes."""

from __future__ import annotations

import re

from mdd.prose.classify.lines import Line, LineClass

BQ = re.compile(r"(?: {0,3}>[ \t]?)+")
TBREAK = re.compile(r"^ {0,3}([-*_])[ \t]*(?:\1[ \t]*){2,}$")
SETEXT = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
#: One container marker at the start of a line: a list marker, a footnote label
#: or a block-quote marker, and the whitespace after it.
_CONTAINER_MARKER = re.compile(
    r"^(?:[ \t]*(?:[-*+]|\d{1,9}[.)])(?=[ \t]|$)|[ \t]*\[\^[^\]\s]+\]:| {0,3}>)(?P<gap>[ \t]*)"
)
_INDENT = re.compile(r"^[ \t]*")

INDENTED_CODE_COLUMN = 4


def strip_quote(raw: str) -> tuple[str, str]:
    """Split *raw* into its block-quote prefix and the remainder."""
    match = BQ.match(raw)
    if match is None or match.end() == 0:
        return "", raw
    return raw[: match.end()], raw[match.end() :]


#: The only characters Markdown treats as horizontal whitespace. `str.strip()`
#: with no argument also eats U+00A0 and friends, which are *content*: deleting
#: a leading no-break space turns a paragraph into whatever its first character
#: then spells — a fence, a heading, a list item.
MD_SPACE = " \t"

_TAB_STOP = 4


def indent_bytes(text: str) -> str:
    """Return *text*'s leading indent verbatim, so a rewriter can re-emit it."""
    return _INDENT.match(text).group(0)  # pyright: ignore[reportOptionalMemberAccess]


def columns(text: str, start: int = 0) -> int:
    """Return the column *text* ends at when it begins at column *start*.

    Tabs expand to 4-column stops. Character count is the wrong measure: a
    single leading tab is four columns, which is the difference between a
    paragraph and an indented code block.
    """
    column = start
    for char in text:
        column += _TAB_STOP - (column % _TAB_STOP) if char == "\t" else 1
    return column


def indent_columns(text: str) -> int:
    """Return the indent's width in columns, expanding tabs to 4-column stops."""
    return columns(indent_bytes(text))


def _hard_break(text: str) -> bool:
    return text.endswith(("  ", "\\")) and bool(text.strip(MD_SPACE))


def _continuation_markers(markers: str, column: int) -> str:
    """Return what a continuation line needs in place of *markers*.

    *markers* starts at *column*. A list marker or footnote label becomes as
    many spaces as it is wide, and a block-quote marker is kept, since a
    continuation line needs it to stay inside the quote.
    """
    out = ""
    rest = markers
    while (match := _CONTAINER_MARKER.match(rest)) is not None and match.end() > 0:
        piece = match.group(0)
        end = columns(piece, column)
        out += piece if piece.lstrip(MD_SPACE).startswith(">") else " " * (end - column)
        column = end
        rest = rest[match.end() :]
    return out


def prose_line(number: int, raw: str, quote: str, rest: str, *, markers: bool = True) -> Line:
    """Build a PROSE line, deriving the prefix and continuation prefix.

    Every container marker that opens the line is prefix, nested ones
    included: in ``- > - a`` the paragraph starts at ``a``. With *markers*
    false the line continues a paragraph, and a marker on it is text.
    """
    split = split_markers(rest) if markers else None
    if split is not None:
        found = split[0]
        return Line(
            number=number,
            text=raw,
            cls=LineClass.PROSE,
            prefix=quote + found,
            cont_prefix=quote + _continuation_markers(found, columns(quote)),
            hard_break=_hard_break(raw),
        )
    indent = indent_bytes(rest)
    return Line(
        number=number,
        text=raw,
        cls=LineClass.PROSE,
        prefix=quote + indent,
        cont_prefix=quote + indent,
        hard_break=_hard_break(raw),
    )


def quote_depth(quote: str) -> int:
    return quote.count(">")


ONE_QUOTE = re.compile(r"[ \t]*>[ \t]?")


#: Five or more columns of whitespace after a list marker mean the content
#: starts one column after the marker and the rest is indented code.
_MAX_MARKER_GAP = 4


def gap_is_code(markers: str, gap: str) -> bool:
    """True when *gap*, the whitespace that ends *markers*, starts indented code.

    The content of the last marker then starts one column after it, and a
    marker further along the line is code, not the start of a nested item.
    """
    marker_end = columns(markers[: len(markers) - len(gap)])
    return columns(gap, marker_end) - marker_end > _MAX_MARKER_GAP


def list_content_column(indent: str, marker: str, gap: str) -> int:
    """Return the column a list item's content starts at, per CommonMark.

    Measured in columns, not characters: a tab before or after the marker is up
    to four columns wide, and counting it as one put the indented-code floor
    too low. *gap* is the whitespace between the marker and the content, empty
    for a bare marker, whose content can only start one column further in.
    """
    marker_end = columns(marker, columns(indent))
    content = columns(gap, marker_end)
    if not gap or content - marker_end > _MAX_MARKER_GAP:
        return marker_end + 1
    return content


def drop_columns(text: str, count: int) -> str:
    """Remove *count* columns of leading whitespace from *text*.

    A tab that straddles the boundary leaves its remaining columns behind as
    spaces, as CommonMark does.
    """
    column = 0
    index = 0
    while index < len(text) and column < count and text[index] in MD_SPACE:
        column = columns(text[index], column)
        index += 1
    return " " * (column - count) + text[index:]


def split_markers(rest: str) -> tuple[str, str, str] | None:
    """Split *rest* into its container markers, the gap after the last one, and the rest.

    ``None`` when *rest* does not start with a list marker or footnote label.
    *rest* has had its block-quote markers removed already, so a match here is
    one of those two. The markers may nest: ``- 1. > # h`` is a heading three
    containers deep.
    """
    if _CONTAINER_MARKER.match(rest) is None:
        return None
    markers = ""
    gap = ""
    content = rest
    while (match := _CONTAINER_MARKER.match(content)) is not None and match.end() > 0:
        if markers and TBREAK.match(content):
            break
        markers += match.group(0)
        gap = match.group("gap")
        content = content[match.end() :]
        if gap_is_code(markers, gap):
            break
    return markers, gap, content
