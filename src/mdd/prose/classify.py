"""The shared line classifier every prose check consumes.

Produced once per file. Five checks each with their own idea of where a fenced
block ends will disagree on an edge case, and the reflow will then rewrite a
line the lint told the author was code. One classifier makes that class of bug
impossible rather than unlikely.

The classifier fails closed: an unbalanced fence, an unterminated HTML comment
or frontmatter that never closes yields a :class:`ClassifyError`, and the file
is skipped by every check — and never written to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from markdown_it.common.html_blocks import block_names

from mdd.markdown.ir.callouts import div_opener
from mdd.prose.inline import LinkRef, Span, scan

if TYPE_CHECKING:
    from collections.abc import Sequence

_BQ = re.compile(r"(?: {0,3}>[ \t]?)+")
_BQ_ANY_INDENT = re.compile(r"(?:[ \t]*>[ \t]?)+")
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_ATX = re.compile(r"^ {0,3}#{1,6}(\s|$)")
_TBREAK = re.compile(r"^ {0,3}([-*_])[ \t]*(?:\1[ \t]*){2,}$")
_SETEXT = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
_LIST = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])([ \t]+)(?=\S)")
_LIST_BARE = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])[ \t]*$")
_LINK_DEF = re.compile(r"^ {0,3}\[[^\]^]+\]:[ \t]*\S+")
_LINK_LABEL_ONLY = re.compile(r"^ {0,3}\[[^\]^]+\]:[ \t]*$")
_LINK_DEF_TAIL = re.compile(r"^ {0,3}\[[^\]^]+\]:[ \t]*\S+[ \t]*(.*)$")
_LINK_TITLE_START = re.compile(r"^[ \t]*[\"'(]")
_FOOTNOTE_DEF = re.compile(r"^([ \t]*\[\^[^\]\s]+\]:[ \t]*)(?=\S)")
#: One container marker at the start of a line: a list marker, a footnote label
#: or a block-quote marker, and the whitespace after it.
_CONTAINER_MARKER = re.compile(
    r"^(?:[ \t]*(?:[-*+]|\d{1,9}[.)])(?=[ \t]|$)|[ \t]*\[\^[^\]\s]+\]:| {0,3}>)(?P<gap>[ \t]*)"
)
_HTML_BLOCK = re.compile(r"^ {0,3}</?[A-Za-z!?]")
#: HTML blocks that end at a closing marker rather than at a blank line, with
#: that marker. Each may contain blank lines, and each may interrupt a paragraph.
_HTML_RAW_BLOCKS: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    (
        re.compile(r"^ {0,3}<(?:script|pre|style|textarea)(?=[ \t>]|$)", re.IGNORECASE),
        re.compile(r"</(?:script|pre|style|textarea)>", re.IGNORECASE),
    ),
    (re.compile(r"^ {0,3}<\?"), re.compile(r"\?>")),
    (re.compile(r"^ {0,3}<![A-Za-z]"), re.compile(r">")),
    (re.compile(r"^ {0,3}<!\[CDATA\["), re.compile(r"\]\]>")),
)
#: An HTML block opened by a block-level tag name. It ends at a blank line and,
#: unlike any other tag, may interrupt a paragraph.
_HTML_BLOCK_TAG = re.compile(
    r"^ {0,3}</?(?:" + "|".join(block_names) + r")(?=[ \t]|/?>|$)", re.IGNORECASE
)
#: A table's delimiter row. One column is enough; the caller also requires a pipe.
_DELIM_ROW = re.compile(r"^[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
_MATH_FENCE = re.compile(r"^ {0,3}\$\$")
_MATH_LABEL_END = re.compile(r"\$\$[ \t]*\([^)$\r\n]+?\)$")
_DIV_CLOSER = re.compile(r"^[ \t]*(:{3,})\s*$")
_ALERT_MARKER = re.compile(r"^\[!\w+\]$")
_MANAGED_CALLOUT = re.compile(r"^\*\*(?:Confluence|SharePoint) export\*\*")
_INDENT = re.compile(r"^[ \t]*")

_INDENTED_CODE_COLUMN = 4
_BYTE_ORDER_MARK = "\ufeff"

#: How deep a line's containers may nest, counting a block quote as one level
#: and a list item as two, as markdown-it does. markdown-it stops parsing at
#: twenty and drops what lies below unseen, so neither it nor the write gate
#: can vouch for an edit there. Two short of that, as the list model guesses.
_MAX_NESTING = 18


class LineClass(StrEnum):
    """What one source line is."""

    FRONTMATTER = "frontmatter"
    FENCED_CODE = "fenced-code"
    INDENTED_CODE = "indented-code"
    HTML_BLOCK = "html-block"
    HTML_COMMENT = "html-comment"
    TABLE = "table"
    BLOCK_QUOTE = "block-quote"
    HEADING = "heading"
    THEMATIC_BREAK = "thematic-break"
    LINK_DEF = "link-target"
    MATH = "math"
    BLANK = "blank"
    #: A ``:::``/``::::`` fenced-div marker (callouts, layouts). Its body is
    #: ordinary prose and is reflowed; the marker line itself never is.
    DIV_MARKER = "div-marker"
    #: A region a rewriter must pass through byte-for-byte: an mdd-managed
    #: export callout, or a callout marker line such as ``> [!NOTE]``. Joining
    #: one into the paragraph below it changes what the file renders as.
    MANAGED = "managed-region"
    #: A list item or footnote marker line whose content is not paragraph text:
    #: an empty item, whose content, if any, starts on a later line.
    LIST_MARKER = "list-marker"
    #: A line markdown-it and CommonMark renderers such as GitHub's read
    #: differently, so that an edit safe for one may change the other. Passed
    #: through byte for byte.
    DIVERGENT = "divergent"
    PROSE = "prose"


@dataclass(frozen=True)
class Line:
    """One classified source line.

    ``prefix`` is the leading bytes a rewriter must preserve verbatim — block
    quote markers, a list marker, the indent. ``cont_prefix`` is what a
    generated continuation line must start with so the block still parses.
    """

    number: int
    text: str
    cls: LineClass
    prefix: str = ""
    cont_prefix: str = ""
    masks: tuple[Span, ...] = ()
    links: tuple[LinkRef, ...] = ()
    block: int = -1
    hard_break: bool = False
    #: The block-quote markers the scan found at the start of the line.
    quote: str = ""

    @property
    def content(self) -> str:
        """The line's text with its preserved prefix removed."""
        return self.text[len(self.prefix) :]


@dataclass(frozen=True)
class Classified:
    """A whole file's classification, plus the byte-level facts a writer needs."""

    lines: tuple[Line, ...]
    newline: str
    final_newline: bool


@dataclass(frozen=True)
class ClassifyError:
    """Why a file could not be classified.

    A value rather than an exception: one unparseable file must not end a
    corpus-wide run.
    """

    line: int
    reason: str


def newline_style(text: str) -> str | None:
    """Return the file's single line-ending convention, or ``None`` if it mixes them.

    Splitting on one terminator when the file uses two leaves the other embedded
    inside a "line", so the classifier mis-scans it and a rewriter silently drops
    or moves bytes. There is no correct choice to make on the user's behalf, so a
    mixed file fails closed instead.
    """
    crlf = text.count("\r\n")
    counts = {
        "\r\n": crlf,
        "\n": text.count("\n") - crlf,
        "\r": text.count("\r") - crlf,
    }
    present = [style for style, count in counts.items() if count]
    if len(present) > 1:
        return None
    return present[0] if present else "\n"


def split_lines(text: str) -> tuple[list[str], str, bool]:
    """Split *text* into lines, returning its newline and whether one trails."""
    newline = newline_style(text) or "\n"
    final_newline = text.endswith(newline)
    body = text[: -len(newline)] if final_newline else text
    if not body and final_newline:
        return [], newline, True
    return body.split(newline), newline, final_newline


def join_lines(lines: list[str], newline: str, *, final_newline: bool) -> str:
    """Inverse of :func:`split_lines`."""
    body = newline.join(lines)
    return body + newline if final_newline else body


def _strip_quote(raw: str) -> tuple[str, str]:
    """Split *raw* into its block-quote prefix and the remainder."""
    match = _BQ.match(raw)
    if match is None or match.end() == 0:
        return "", raw
    return raw[: match.end()], raw[match.end() :]


#: The only characters Markdown treats as horizontal whitespace. `str.strip()`
#: with no argument also eats U+00A0 and friends, which are *content*: deleting
#: a leading no-break space turns a paragraph into whatever its first character
#: then spells — a fence, a heading, a list item.
MD_SPACE = " \t"

_TAB_STOP = 4


def _indent_bytes(text: str) -> str:
    """Return *text*'s leading indent verbatim, so a rewriter can re-emit it."""
    return _INDENT.match(text).group(0)  # pyright: ignore[reportOptionalMemberAccess]


def _columns(text: str, start: int = 0) -> int:
    """Return the column *text* ends at when it begins at column *start*.

    Tabs expand to 4-column stops. Character count is the wrong measure: a
    single leading tab is four columns, which is the difference between a
    paragraph and an indented code block.
    """
    column = start
    for char in text:
        column += _TAB_STOP - (column % _TAB_STOP) if char == "\t" else 1
    return column


def _indent_columns(text: str) -> int:
    """Return the indent's width in columns, expanding tabs to 4-column stops."""
    return _columns(_indent_bytes(text))


def _hard_break(text: str) -> bool:
    return text.endswith(("  ", "\\")) and bool(text.strip(MD_SPACE))


@dataclass
class _State:
    """Mutable block-level scanner state."""

    in_frontmatter: bool = False
    fence: str | None = None
    fence_quote_depth: int = 0
    fence_indent: int = 0
    in_comment: bool = False
    in_math: bool = False
    in_html_block: bool = False
    #: What ends the open HTML block: a closing marker, or ``None`` for a blank line.
    html_end: re.Pattern[str] | None = None
    in_indented_code: bool = False
    #: The content columns of the open list items, innermost last.
    list_cols: list[int] = field(default_factory=list)
    #: The content column of the list item the open fence sits in. A line
    #: indented less than this ends the item, and the fence with it.
    fence_container: int = 0
    #: The previous line was paragraph text, which an indented code block or a
    #: bare-tag HTML block cannot interrupt. A blank line is not the only thing
    #: that ends a paragraph: a heading, a fence or a rule does too.
    in_paragraph: bool = False
    after_div_marker: bool = False
    after_empty_item: bool = False
    #: How many block quotes deep the open paragraph is.
    paragraph_depth: int = 0
    #: A link reference definition is still open: its destination or its title
    #: has yet to come, so the lines that follow belong to it.
    in_link_def: bool = False
    after_link_def: bool = False
    open_at: int = 0
    #: The closing marker of a fenced div opened inside a list item, the
    #: item's content column, and the first line the renderer would drop.
    list_div: str | None = None
    list_div_column: int = 0
    #: How many block quotes the previous line left open.
    open_quotes: int = 0
    #: The colon run and block-quote depth of every open fenced div, outermost first.
    divs: list[tuple[str, int]] = field(default_factory=list)
    dropped: ClassifyError | None = None
    #: The block-quote depth and the container's content column of the open
    #: table, whose rows must sit at both.
    table: tuple[int, int] | None = None
    #: The open list items' content columns before the line being scanned,
    #: and before the one above it.
    cols_before_line: list[int] = field(default_factory=list)
    cols_before_previous: list[int] = field(default_factory=list)
    #: Line numbers markdown-it and CommonMark disagree on: lines whose whole
    #: paragraph is in doubt, and lines that put only the line above in doubt.
    divergent_paragraphs: set[int] = field(default_factory=set)
    divergent_lines: set[int] = field(default_factory=set)
    #: The content column of the list item the open block quote started in.
    quote_base: int = 0


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
        end = _columns(piece, column)
        out += piece if piece.lstrip(MD_SPACE).startswith(">") else " " * (end - column)
        column = end
        rest = rest[match.end() :]
    return out


def _prose_line(number: int, raw: str, quote: str, rest: str, *, markers: bool = True) -> Line:
    """Build a PROSE line, deriving the prefix and continuation prefix.

    Every container marker that opens the line is prefix, nested ones
    included: in ``- > - a`` the paragraph starts at ``a``. With *markers*
    false the line continues a paragraph, and a marker on it is text.
    """
    split = _split_markers(rest) if markers else None
    if split is not None:
        found = split[0]
        return Line(
            number=number,
            text=raw,
            cls=LineClass.PROSE,
            prefix=quote + found,
            cont_prefix=quote + _continuation_markers(found, _columns(quote)),
            hard_break=_hard_break(raw),
        )
    indent = _indent_bytes(rest)
    return Line(
        number=number,
        text=raw,
        cls=LineClass.PROSE,
        prefix=quote + indent,
        cont_prefix=quote + indent,
        hard_break=_hard_break(raw),
    )


def _quote_depth(quote: str) -> int:
    return quote.count(">")


def _opens_fence(rest: str, fence: re.Match[str]) -> bool:
    """True when a fence-shaped line really opens a fenced block.

    CommonMark 4.5: the info string of a backtick fence may not contain a
    backtick. Without that condition a paragraph beginning ``` ```a `b` ``` ```
    opened a block, and everything up to the next fence-shaped line — including
    a genuine code block — became prose the fixers would rewrite.
    """
    return fence.group(1)[0] != "`" or "`" not in rest[fence.end() :]


def _closes_fence(rest: str, quote: str, state: _State) -> bool:
    """True when this line closes the open fence.

    A closer must sit in the same block-quote container as the opener and be no
    more than three columns further indented. Without those two conditions a
    ``>``-prefixed or deeply indented ``` inside a fenced block closed it, and
    the remainder of the code became prose the fixers would rewrite.
    """
    fence = state.fence
    if fence is None or _quote_depth(quote) != state.fence_quote_depth:
        return False
    closer = _FENCE.match(rest)
    if closer is None or closer.group(1)[0] != fence[0] or len(closer.group(1)) < len(fence):
        return False
    if _indent_columns(rest) > state.fence_indent + 3:
        return False
    return not rest[closer.end() :].strip(MD_SPACE)


_ONE_QUOTE = re.compile(r"[ \t]*>[ \t]?")


def _leaves_fence_container(raw: str, state: _State) -> bool:
    """True when *raw* ends the container the open fence is in, and so the fence.

    A fence is not a paragraph, so it has no lazy continuation: a line with
    fewer ``>`` than the fence's opener ends its block quote, and a non-blank
    line indented less than its list item's content column ends the item. The
    indent is measured inside the fence's own block quotes; a ``>`` beyond
    those is fence content. Treating either as fence content let a later
    fence-shaped line close the block, and the code after that read as prose.
    """
    inside = raw
    for _ in range(state.fence_quote_depth):
        marker = _ONE_QUOTE.match(inside)
        if marker is None:
            return True
        inside = inside[marker.end() :]
    return bool(inside.strip(MD_SPACE)) and _indent_columns(inside) < state.fence_container


def _continuation(number: int, raw: str, quote: str, rest: str, state: _State) -> Line | None:
    """Classify *raw* against an open multi-line construct, or return ``None``."""
    if state.in_frontmatter:
        state.in_frontmatter = rest.strip(MD_SPACE) not in ("---", "...")
        return Line(number, raw, LineClass.FRONTMATTER)
    if state.fence is not None:
        if _leaves_fence_container(raw, state):
            state.fence = None
            return None
        if _closes_fence(rest, quote, state):
            state.fence = None
        return Line(number, raw, LineClass.FENCED_CODE)
    if state.in_comment:
        state.in_comment = "-->" not in rest
        return Line(number, raw, LineClass.HTML_COMMENT)
    return _continuation_tail(number, raw, rest, state)


def _closes_math(text: str) -> bool:
    """True when *text* ends a math block: it ends in ``$$``, or in ``$$`` and a label.

    The closer need not be alone on its line: ``c $$`` ends the block, and so
    the line after it is not maths. A trailing no-break space is content, so
    ``$$`` followed by one does not close the block; closing early hands the
    rest of the maths to the fixers as prose.
    """
    stripped = text.strip(MD_SPACE)
    return stripped.endswith("$$") or _MATH_LABEL_END.search(stripped) is not None


def _continuation_tail(number: int, raw: str, rest: str, state: _State) -> Line | None:
    """The second half of :func:`_continuation`: math blocks and HTML blocks."""
    if state.in_math:
        state.in_math = not _closes_math(rest)
        return Line(number, raw, LineClass.MATH)
    if not state.in_html_block:
        return None
    if state.html_end is not None:
        state.in_html_block = state.html_end.search(rest) is None
        return Line(number, raw, LineClass.HTML_BLOCK)
    if rest.strip(MD_SPACE):
        return Line(number, raw, LineClass.HTML_BLOCK)
    state.in_html_block = False
    return Line(number, raw, LineClass.BLANK)


def _open_html_block(rest: str, state: _State) -> bool:
    """Open an HTML block at *rest* if one starts there, and say whether it did.

    Mirrors CommonMark's seven kinds closely enough to fail closed. ``<pre>``,
    ``<script>``, processing instructions and the like run to their closing
    marker, blank lines included; ending them at the first blank line handed
    their tail to the fixers as prose. Those kinds and the block-level tag names
    may interrupt a paragraph. Any other tag-shaped line opens a block only
    after a blank line, so a mid-paragraph ``<https://…>`` stays prose.
    """
    for opener, end in _HTML_RAW_BLOCKS:
        opened = opener.match(rest)
        if opened is not None:
            state.in_html_block = end.search(rest, opened.end()) is None
            state.html_end = end
            return True
    if _HTML_BLOCK_TAG.match(rest) or (not state.in_paragraph and _HTML_BLOCK.match(rest)):
        state.in_html_block = True
        state.html_end = None
        return True
    return False


def _open_block(number: int, raw: str, quote: str, rest: str, state: _State) -> Line | None:
    """Classify *raw* as the opening line of a multi-line construct, or ``None``."""
    fence = _FENCE.match(rest)
    if fence is not None and _opens_fence(rest, fence):
        state.fence = fence.group(1)
        state.fence_quote_depth = _quote_depth(quote)
        state.fence_indent = _indent_columns(rest)
        state.fence_container = 0
        state.open_at = number
        return Line(number, raw, LineClass.FENCED_CODE)
    stripped = rest.lstrip()
    if stripped.startswith("<!--"):
        if "-->" not in stripped[4:]:
            state.in_comment = True
            state.open_at = number
        return Line(number, raw, LineClass.HTML_COMMENT)
    if _MATH_FENCE.match(rest):
        # A math block is one line only when the opener carries its own closer;
        # `$$`, `$$$` and `$$ a` all open a block that runs to a later line.
        if len(rest.strip(MD_SPACE)) <= len("$$$") or not _closes_math(rest):
            state.in_math = True
            state.open_at = number
        return Line(number, raw, LineClass.MATH)
    # A fenced-div opener. Its body is ordinary prose and is reflowed; the
    # marker line is not. Joining `:::callout-tip` into the paragraph below it
    # destroys the callout, which is a first-class construct in the IR. A
    # colon run with a name the renderer does not know is paragraph text.
    fence = div_opener(rest.lstrip(MD_SPACE))
    if fence is not None:
        state.divs.append((fence, _quote_depth(quote)))
        return Line(number, raw, LineClass.DIV_MARKER)
    if _open_html_block(rest, state):
        return Line(number, raw, LineClass.HTML_BLOCK)
    return None


def _close_items(rest: str, state: _State) -> None:
    """Close every open list item that *rest*, starting a block, is indented less than.

    Called for every fresh line that starts a block, not only the ones that end
    up as prose. A heading, a fence or a thematic break at column zero ends the
    list just as a paragraph does, and leaving the content column set after one
    raised the indented-code floor so a genuine four-space code block read as
    prose, and the fixers then rewrote its interior.
    """
    if not rest.strip(MD_SPACE):
        return
    indent = _indent_columns(rest)
    while state.list_cols and state.list_cols[-1] > indent:
        _ = state.list_cols.pop()


def _container_column(indent: int, state: _State) -> int:
    """Return the content column of the innermost open item a line at *indent* is in."""
    return max((column for column in state.list_cols if column <= indent), default=0)


#: Five or more columns of whitespace after a list marker mean the content
#: starts one column after the marker and the rest is indented code.
_MAX_MARKER_GAP = 4


def _gap_is_code(markers: str, gap: str) -> bool:
    """True when *gap*, the whitespace that ends *markers*, starts indented code.

    The content of the last marker then starts one column after it, and a
    marker further along the line is code, not the start of a nested item.
    """
    marker_end = _columns(markers[: len(markers) - len(gap)])
    return _columns(gap, marker_end) - marker_end > _MAX_MARKER_GAP


def _list_content_column(indent: str, marker: str, gap: str) -> int:
    """Return the column a list item's content starts at, per CommonMark.

    Measured in columns, not characters: a tab before or after the marker is up
    to four columns wide, and counting it as one put the indented-code floor
    too low. *gap* is the whitespace between the marker and the content, empty
    for a bare marker, whose content can only start one column further in.
    """
    marker_end = _columns(marker, _columns(indent))
    content = _columns(gap, marker_end)
    if not gap or content - marker_end > _MAX_MARKER_GAP:
        return marker_end + 1
    return content


def _interrupts_paragraph(rest: str) -> bool:
    """True when the list item on *rest* may interrupt a paragraph.

    Only an item with content may, and of ordered items only one numbered 1. A
    bare `-` under a paragraph is a setext underline, and `10. x` continues it.
    """
    item = _LIST.match(rest)
    if item is None:
        return False
    number = item.group(2)[:-1]
    return not number or number == "1"


def _continues_paragraph_text(rest: str, state: _State) -> bool:
    """True when a list marker on *rest* is paragraph text rather than a new item.

    A marker that cannot interrupt a paragraph continues it, unless it sits
    left of the paragraph's list item: then it starts a sibling item. A colon
    run kept as a possible div closer may be paragraph text too, so an item
    after one may be continuing a paragraph. Opening fewer
    items is the safe guess: it only lowers the indented-code floor.
    """
    paragraph = state.in_paragraph or state.after_div_marker
    innermost = state.list_cols[-1] if state.list_cols else 0
    return paragraph and not _interrupts_paragraph(rest) and _indent_columns(rest) >= innermost


def _open_items(rest: str, state: _State) -> bool:
    """Open one list item per marker *rest* starts with; say whether there was one.

    Markers nest, as in ``- 1. a``, and each opens an item one level deeper. A
    run like ``* * *`` after the first marker is a thematic break, not more
    items. A marker after a gap wide enough to start indented code is code,
    not another item.
    """
    consumed = 0
    while (item := _LIST.match(rest[consumed:]) or _LIST_BARE.match(rest[consumed:])) is not None:
        if consumed and _TBREAK.match(rest[consumed:]):
            break
        if not consumed:
            _close_items(rest, state)
        gap = item.group(3) if item.re is _LIST else ""
        column = _list_content_column(item.group(1), item.group(2), gap)
        state.list_cols.append(_columns(rest[:consumed]) + column)
        consumed += item.end()
        if _gap_is_code(rest[:consumed], gap):
            break
    return consumed > 0


def _track_list(rest: str, state: _State) -> None:
    """Open the list items *rest* starts, or close the ones it ends.

    A lazy paragraph continuation is less indented than its item and still
    belongs to it, so a line inside a paragraph closes nothing.
    """
    if _continues_paragraph_text(rest, state):
        if not state.in_paragraph:
            _close_items(rest, state)
        return
    if not _open_items(rest, state) and not state.in_paragraph:
        _close_items(rest, state)


def _is_indented_code(rest: str, state: _State) -> bool:
    """True when *rest* belongs to an indented code block.

    An indented code block *opens* anywhere except inside a paragraph, but it
    *continues* for as long as the indent holds. Requiring a preceding blank on
    every line classified only the block's first line as code and handed the
    rest to the rewriters as prose; requiring one before the first line did the
    same to a code block straight after a heading.
    """
    if state.in_paragraph and not state.in_indented_code:
        return False
    indent = _indent_columns(rest)
    return indent >= _INDENTED_CODE_COLUMN + _container_column(indent, state)


def _single_line_class(rest: str) -> LineClass | None:
    """Return the class of a line that is a whole block by itself, or ``None``."""
    if _ATX.match(rest):
        return LineClass.HEADING
    if _TBREAK.match(rest):
        return LineClass.THEMATIC_BREAK
    if _LINK_DEF.match(rest) or _LINK_LABEL_ONLY.match(rest):
        return LineClass.LINK_DEF
    return None


def _unclosed_title(rest: str) -> bool:
    """True when the link definition on *rest* opens a title it does not close."""
    tail = _LINK_DEF_TAIL.match(rest)
    if tail is None:
        return False
    title = tail.group(1).rstrip(MD_SPACE)
    if not title or title[0] not in "\"'(":
        return False
    closer = ")" if title[0] == "(" else title[0]
    return len(title) < 2 or title[-1] != closer


def _link_definition(line: Line, rest: str, state: _State) -> Line:
    """Extend a link reference definition over the lines that continue it.

    A definition may put its destination, or its title, on a later line, and a
    title may run over several. Reproducing that grammar is not worth it, so
    this fails closed: once a definition is incomplete, every line that would
    otherwise be paragraph text is called part of it until something else ends
    the run. A paragraph glued to a definition loses its checks; no line of a
    definition is ever handed to a fixer.
    """
    continues = state.in_link_def or (
        state.after_link_def and _LINK_TITLE_START.match(rest) is not None
    )
    if line.cls is LineClass.PROSE and continues:
        line = Line(line.number, line.text, LineClass.LINK_DEF)
        state.in_link_def = True
    elif line.cls is LineClass.LINK_DEF:
        split = _split_markers(rest)
        definition = (split[2] if split is not None else rest).lstrip(MD_SPACE)
        state.in_link_def = bool(_LINK_LABEL_ONLY.match(definition)) or _unclosed_title(definition)
    else:
        state.in_link_def = False
    state.after_link_def = line.cls is LineClass.LINK_DEF
    return line


def _drop_columns(text: str, count: int) -> str:
    """Remove *count* columns of leading whitespace from *text*.

    A tab that straddles the boundary leaves its remaining columns behind as
    spaces, as CommonMark does.
    """
    column = 0
    index = 0
    while index < len(text) and column < count and text[index] in MD_SPACE:
        column = _columns(text[index], column)
        index += 1
    return " " * (column - count) + text[index:]


def _container_content(rest: str, state: _State) -> str:
    """Return *rest* as the open list item sees it, without the item's indent.

    A block opener may be indented at most three columns *within its
    container*. Measuring from the margin instead called a heading, maths or an
    HTML block at a list item's content column prose. A line indented less
    than the content column is outside the item and is measured as it stands.
    """
    column = _container_column(_indent_columns(rest), state)
    return _drop_columns(rest, column) if column else rest


def _split_markers(rest: str) -> tuple[str, str, str] | None:
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
        if markers and _TBREAK.match(content):
            break
        markers += match.group(0)
        gap = match.group("gap")
        content = content[match.end() :]
        if _gap_is_code(markers, gap):
            break
    return markers, gap, content


def _marker_line(number: int, raw: str, quote: str, rest: str, state: _State) -> Line | None:
    """Classify a list item or footnote line by the block its content opens.

    The content after a marker is the first block of a new item, so it may be
    anything a line on its own may be: a heading, a rule, a fence, maths, an
    HTML block, a link definition, indented code, or nothing at all. Calling
    those prose handed them to the fixers. ``None`` when the content is
    paragraph text, or *rest* carries no marker.
    """
    split = _split_markers(rest)
    if split is None:
        return None
    markers, gap, content = split
    prefix = quote + markers
    if not content.strip(MD_SPACE):
        return Line(number, raw, LineClass.LIST_MARKER, prefix=prefix)
    # Tabs in the gap expand from the column the marker ends at.
    if _gap_is_code(markers, gap):
        return Line(number, raw, LineClass.INDENTED_CODE, prefix=prefix)
    # Nothing the content opens is interrupting a paragraph: it is the first
    # line of the item. The scan loop recomputes this flag after every line.
    state.in_paragraph = False
    opened = _open_block(number, raw, prefix, content, state)
    if opened is not None:
        if opened.cls is LineClass.FENCED_CODE:
            state.fence_indent = _columns(markers)
            state.fence_container = _container_column(state.fence_indent, state)
        return replace(opened, prefix=prefix)
    single = _single_line_class(content)
    return Line(number, raw, single, prefix=prefix) if single is not None else None


def _close_div(number: int, raw: str, quote: str, rest: str, state: _State) -> Line | None:
    """Classify a bare colon run that may close an open fenced div, or ``None``.

    The renderer closes a div at the first line that is exactly its colon run,
    at any indent. A run that matches no open div is paragraph text. One whose
    block-quote depth differs from its opener's may still close it, through a
    lazy continuation line, so it is a marker but leaves the div open.
    """
    closer = _DIV_CLOSER.match(rest)
    if closer is None:
        return None
    fence = closer.group(1)
    depth = _quote_depth(quote)
    if (fence, depth) in state.divs:
        del state.divs[state.divs.index((fence, depth)) :]
    elif not any(open_fence == fence for open_fence, _ in state.divs):
        return None
    return Line(number, raw, LineClass.DIV_MARKER)


def _classify_fresh(number: int, raw: str, quote: str, rest: str, state: _State) -> Line:
    """Classify a line that is not inside any open multi-line construct."""
    # Indented code is tested first: its contents are literal, so a line inside
    # it that happens to read as `<!--` or a fence must not open a construct.
    if _is_indented_code(rest, state):
        return Line(number, raw, LineClass.INDENTED_CODE)
    inner = _container_content(rest, state)
    opened = _close_div(number, raw, quote, rest, state) or _open_block(
        number, raw, quote, inner, state
    )
    if opened is not None:
        _close_items(rest, state)
        if opened.cls is LineClass.FENCED_CODE:
            state.fence_indent = _indent_columns(rest)
            state.fence_container = _container_column(state.fence_indent, state)
        return opened
    # A one-line block is looked for at any indent that is not code. Which list
    # item a line sits in is a guess, and a wrong guess must not hide a heading
    # or a rule; calling an indented paragraph line one only splits the
    # paragraph, and the writers leave the line alone.
    single = _single_line_class(rest.lstrip(MD_SPACE))
    if single is not None:
        _close_items(rest, state)
        return Line(number, raw, single, prefix=quote)
    # A marker that cannot interrupt the paragraph above it, such as `5.` or
    # `10. a`, is paragraph text, and so is the rest of its line.
    text_marker = state.in_paragraph and _continues_paragraph_text(rest, state)
    _track_list(rest, state)
    if not rest.strip(MD_SPACE):
        return Line(number, raw, LineClass.BLOCK_QUOTE if quote else LineClass.BLANK)
    if text_marker:
        return _prose_line(number, raw, quote, rest, markers=False)
    return _marker_line(number, raw, quote, rest, state) or _prose_line(number, raw, quote, rest)


def _track_list_div(line: Line, rest: str, state: _State) -> None:
    """Fail closed on a fenced div in a list item with a line outside the item.

    The fenced-div renderer looks for its closing marker past the end of the
    list item, and silently drops every line between the first one indented
    less than the item and that marker. Such a line is not prose, nor anything
    else the classifier has a class for, so the file is refused instead.
    """
    content = rest.strip(MD_SPACE)
    if state.list_div is not None:
        dedented = bool(content) and _indent_columns(rest) < state.list_div_column
        if line.cls is LineClass.DIV_MARKER and content == state.list_div:
            state.list_div = None
        elif dedented and state.dropped is None:
            state.dropped = ClassifyError(
                line.number, "a fenced div in a list item drops a less-indented line"
            )
        return
    if line.cls is not LineClass.DIV_MARKER:
        return
    split = _split_markers(rest)
    if split is None:
        indent, opener = _indent_columns(rest), div_opener(rest.lstrip(MD_SPACE))
    else:
        indent, opener = _columns(split[0]), div_opener(split[2].lstrip(MD_SPACE))
    column = _container_column(indent, state)
    if opener is not None and column:
        state.list_div = opener
        state.list_div_column = column


def _strip_open_quote(raw: str, quote: str, rest: str, state: _State) -> tuple[str, str]:
    """Strip the markers of the block quotes the line before left open, at any indent.

    markdown-it continues an open block quote on a ``>`` however far it is
    indented, while a new one may sit at most three columns in. Read as
    paragraph text, a tab-indented quote line handed the fence it opened to
    the fixers.
    """
    if _quote_depth(quote) >= state.open_quotes:
        return quote, rest
    end = 0
    for _ in range(state.open_quotes):
        marker = _ONE_QUOTE.match(raw, end)
        if marker is None:
            break
        end = marker.end()
    nested = _BQ.match(raw, end)
    if nested is not None:
        end = nested.end()
    return raw[:end], raw[end:]


def _open_quotes_after(line: Line, quote: str, rest: str, state: _State) -> int:
    """Return how many block quotes are open after *line*.

    A line without a ``>`` ends every open quote, unless it continues the
    paragraph inside one. A blank line never does, and a list item or footnote
    starts a block of its own.
    """
    depth = _quote_depth(quote)
    if depth:
        return depth
    lazy = line.cls is LineClass.PROSE and state.in_paragraph
    if lazy and not (_LIST.match(rest) or _FOOTNOTE_DEF.match(rest)):
        return state.open_quotes
    return 0


def _strip_quote_in_item(quote: str, rest: str, state: _State) -> tuple[str, str]:
    """Strip a block quote that opens inside a list item, at the item's indent.

    Three columns of indent is the limit for a ``>`` within its container, so
    a quote in a list item may sit further in than that from the margin. Any
    indent is accepted here once a list item is open: a paragraph line taken
    for a quote is only split from its paragraph, while a quote taken for a
    paragraph line hides the code or the rule inside it.
    """
    if not state.list_cols:
        return quote, rest
    match = _BQ_ANY_INDENT.match(rest)
    if match is None:
        return quote, rest
    return quote + rest[: match.end()], rest[match.end() :]


def _in_literal_block(rest: str, state: _State) -> bool:
    """True when *rest* is inside a construct whose lines are literal text."""
    return (
        state.in_frontmatter
        or state.in_comment
        or state.in_math
        or state.in_html_block
        or (state.fence is None and _is_indented_code(rest, state))
    )


def _scan_blocks(raw_lines: list[str]) -> tuple[list[Line], ClassifyError | None, _State]:
    """Run the block-level state machine over *raw_lines*."""
    state = _State()
    out: list[Line] = []
    for index, raw in enumerate(raw_lines):
        number = index + 1
        # A byte order mark is not content: the sync reads the front matter
        # behind one, so the writers must not touch it either.
        if number == 1 and raw.removeprefix(_BYTE_ORDER_MARK).rstrip(MD_SPACE) == "---":
            state.in_frontmatter = True
            state.open_at = 1
            out.append(Line(1, raw, LineClass.FRONTMATTER))
            continue
        state.cols_before_previous = state.cols_before_line
        state.cols_before_line = list(state.list_cols)
        plain_quote, plain_rest = _strip_quote(raw)
        quote, rest = _strip_open_quote(raw, plain_quote, plain_rest, state)
        deep_marker = len(quote) > len(plain_quote) and _deep_quote_marker(quote, state)
        if not _in_literal_block(rest, state):
            quote, rest = _strip_quote_in_item(quote, rest, state)
        deep_lazy = _deep_lazy_line(quote, rest, state)
        # A deeper block quote opens a new container, and no paragraph is open
        # inside it yet. A shallower one is a lazy continuation.
        if _quote_depth(quote) > state.paragraph_depth:
            state.in_paragraph = False
        line = _continuation(number, raw, quote, rest, state) or _classify_fresh(
            number, raw, quote, rest, state
        )
        line = _link_definition(line, rest, state)
        line = _track_table(line, quote, rest, out, state)
        if line.cls is LineClass.PROSE and deep_marker:
            state.divergent_paragraphs.add(number)
        if line.cls is LineClass.PROSE and deep_lazy:
            state.divergent_lines.update((number - 1, number))
        _track_list_div(line, rest, state)
        _track_nesting(number, quote, state)
        line = replace(line, quote=quote)
        if not state.open_quotes and quote:
            column = _indent_columns(quote)
            state.quote_base = max((c for c in state.cols_before_line if c <= column), default=0)
        _after_line(line, quote, rest, state)
        out.append(line)
    return out, _unclosed(state), state


def _deep_quote_marker(quote: str, state: _State) -> bool:
    """True when a ``>`` in *quote* sits four or more columns past its container.

    markdown-it continues an open block quote on such a marker; CommonMark
    reads the line as indented code, or as paragraph text with a literal
    ``>``. The first marker is measured from the content column of the list
    item the quote started in, the others from the end of the marker before.
    """
    column = 0
    position = 0
    first = True
    while (marker := _ONE_QUOTE.match(quote, position)) is not None and marker.end() > position:
        indent = _indent_bytes(quote[position:])
        start = _columns(indent, column)
        base = state.quote_base if first else column
        if start - base >= _INDENTED_CODE_COLUMN:
            return True
        column = _columns(quote[position + len(indent) : marker.end()], start)
        position = marker.end()
        first = False
    return False


def _deep_lazy_line(quote: str, rest: str, state: _State) -> bool:
    """True when *rest* is a lazy line, indented four or more, of a quoted paragraph.

    markdown-it may end the paragraph there and start indented code, where
    CommonMark reads one more paragraph line, so a hard break at the end of
    the line above means something only to CommonMark.
    """
    if not state.in_paragraph or _quote_depth(quote) >= state.paragraph_depth:
        return False
    if not rest.strip(MD_SPACE):
        return False
    indent = _indent_columns(rest)
    return indent - _container_column(indent, state) >= _INDENTED_CODE_COLUMN


def _apply_divergent(
    lines: list[Line], divergent_paragraphs: set[int], lines_only: set[int]
) -> None:
    """Make the prose lines renderers disagree on, and their paragraphs, divergent."""
    blocks = {
        line.block
        for line in lines
        if line.number in divergent_paragraphs and line.cls is LineClass.PROSE
    }
    for index, line in enumerate(lines):
        if line.cls is not LineClass.PROSE:
            continue
        if line.block in blocks or line.number in lines_only:
            lines[index] = replace(line, cls=LineClass.DIVERGENT, block=-1, cont_prefix="")


#: What the scan may have called a line that is really a table row. A link
#: definition or maths cannot interrupt a table, so a line shaped like one is
#: just another row.
_TABLE_ROW_CLASSES = (LineClass.PROSE, LineClass.LINK_DEF, LineClass.MATH)


def _table_line(line: Line) -> Line:
    return replace(line, cls=LineClass.TABLE, prefix="", cont_prefix="")


def _is_table_row(line: Line, quote: str, rest: str, table: tuple[int, int]) -> bool:
    """True when *line*, straight after a row of *table*, is one more row.

    GFM ends a table at a blank line or at the start of another block, not at
    the first line without a pipe, so a line directly under a table is a row,
    and calling it prose let the fixers rewrite a table cell. A row is not a
    paragraph, so it has no lazy continuation: a line indented less than the
    table's list item is outside the item and ends the table.
    """
    depth, column = table
    return (
        line.cls in _TABLE_ROW_CLASSES
        and _quote_depth(quote) == depth
        and _LIST.match(rest) is None
        and _indent_columns(rest) >= column
    )


def _opens_table(rest: str, out: Sequence[Line]) -> bool:
    """True when *rest* is a delimiter row under a header row."""
    if not out or not _DELIM_ROW.match(rest) or "|" not in rest:
        return False
    header = out[-1]
    return header.cls is LineClass.PROSE and "|" in header.text


def _open_table(quote: str, rest: str, out: list[Line], state: _State) -> None:
    """Record the table *rest* opens, and close the list items it shows never opened.

    markdown-it tries a table before a new list, so a header row that starts
    a list is a table in the enclosing container, the marker one of its
    cells, unless the delimiter row is too far indented for that. A header
    row that is the next item of an open list is read by the list instead,
    and its table is in the item.
    """
    header_rest = out[-1].text[len(out[-1].quote) :]
    header_indent = _indent_columns(header_rest)
    delimiter_indent = _indent_columns(rest)
    outer = _container_column(header_indent, state)
    starts_list = not any(column > header_indent for column in state.cols_before_previous)
    if (
        starts_list
        and _split_markers(header_rest) is not None
        and delimiter_indent - outer < _INDENTED_CODE_COLUMN
    ):
        while state.list_cols and state.list_cols[-1] > header_indent:
            _ = state.list_cols.pop()
    while state.list_cols and state.list_cols[-1] > delimiter_indent:
        _ = state.list_cols.pop()
    state.table = (_quote_depth(quote), _container_column(delimiter_indent, state))
    out[-1] = _table_line(out[-1])


def _track_table(line: Line, quote: str, rest: str, out: list[Line], state: _State) -> Line:
    """Classify *line* as a table row when it is one, opening or continuing a table.

    A row's content is never maths or a link definition, so whatever the
    scan opened for one is dropped.
    """
    if state.table is not None and _is_table_row(line, quote, rest, state.table):
        state.in_math = state.in_link_def = False
        return _table_line(line)
    state.table = None
    if _opens_table(rest, out):
        _open_table(quote, rest, out, state)
        state.in_math = state.in_link_def = False
        return _table_line(line)
    return line


def _track_nesting(number: int, quote: str, state: _State) -> None:
    """Fail closed on a line nested deeper than markdown-it parses."""
    depth = _quote_depth(quote) + 2 * len(state.list_cols)
    if depth >= _MAX_NESTING and state.dropped is None:
        state.dropped = ClassifyError(number, "the document nests too deeply to check")


def _after_line(line: Line, quote: str, rest: str, state: _State) -> None:
    """Carry what *line* turned out to be over to the classification of the next one."""
    blank = line.cls in (LineClass.BLANK, LineClass.BLOCK_QUOTE)
    # An empty list item followed by a blank line has ended: an item may start
    # with at most one blank line.
    if blank and state.after_empty_item and state.list_cols:
        _ = state.list_cols.pop()
    state.after_empty_item = line.cls is LineClass.LIST_MARKER
    state.open_quotes = _open_quotes_after(line, quote, rest, state)
    # An incomplete link definition reads on like a paragraph: indented code
    # cannot interrupt it either.
    state.in_paragraph = state.in_link_def or (
        line.cls is LineClass.PROSE and not (state.in_paragraph and _SETEXT.match(rest))
    )
    if line.cls is LineClass.PROSE:
        state.paragraph_depth = _quote_depth(quote)
    state.after_div_marker = line.cls is LineClass.DIV_MARKER
    # A blank line does not end an indented code block — it is content inside
    # one — so the flag survives a blank and only a shallower non-blank line
    # clears it.
    if not blank:
        state.in_indented_code = line.cls is LineClass.INDENTED_CODE


def _unclosed(state: _State) -> ClassifyError | None:
    """Return why the file cannot be classified once every line has been read."""
    if state.in_frontmatter:
        return ClassifyError(state.open_at, "frontmatter block never closes")
    if state.fence is not None:
        return ClassifyError(state.open_at, "fenced code block never closes")
    if state.in_comment:
        return ClassifyError(state.open_at, "HTML comment never closes")
    if state.in_math:
        return ClassifyError(state.open_at, "math block never closes")
    return state.dropped


def _reclaim_code_blanks(lines: list[Line]) -> None:
    """Reclassify a blank line that sits *between* two indented-code lines.

    Such a line is content of the code block, not a paragraph separator, so
    ``blank-run`` must not delete it. Decided in a post-pass because it needs to
    know whether the code block resumes, which the forward scan cannot.
    """
    #: One forward pass. Re-scanning the whole file from each blank line was
    #: quadratic: 32k lines of ordinary prose spent 0.6s here alone.
    run: list[int] = []
    in_code = False
    for index, line in enumerate(lines):
        if line.cls is LineClass.BLANK:
            run.append(index)
            continue
        if in_code and line.cls is LineClass.INDENTED_CODE:
            for blank in run:
                lines[blank] = replace(lines[blank], cls=LineClass.INDENTED_CODE)
        run.clear()
        in_code = line.cls is LineClass.INDENTED_CODE


def _paragraph_start(lines: Sequence[Line], index: int) -> int:
    """Return the index of the first line of the paragraph *index* belongs to.

    Reads the block numbers :func:`_assign_blocks` gave the prose lines.
    """
    block = lines[index].block
    while index > 0 and lines[index - 1].cls is LineClass.PROSE and lines[index - 1].block == block:
        index -= 1
    return index


def _underlines(underline: str, first: str) -> bool:
    """True when *underline* is a setext underline for a paragraph starting *first*.

    Both are block-quote-stripped. An underline must sit inside the container
    the paragraph is in, at most three columns in. For a list item that is its
    content column, so `- a` over `---` is a list and a rule, while `- a` over
    `  ---` is a heading in the list item. A paragraph that does not open on a
    marker line gets the benefit of the doubt: calling a paragraph a heading
    keeps it from the fixers, the other mistake hands one to them. The
    container is the innermost one: in ``- 1. a`` that is the ``1.`` item.
    """
    if not _SETEXT.match(underline.lstrip(MD_SPACE)):
        return False
    indent = _indent_columns(underline)
    split = _split_markers(first)
    if split is None:
        return indent <= max(_INDENTED_CODE_COLUMN - 1, _indent_columns(first) + 3)
    if ">" in split[0]:
        # A block quote inside the item: where its underline may sit is not
        # worth working out, and a heading is the safe guess.
        return True
    column = _columns(split[0])
    return column <= indent <= column + _INDENTED_CODE_COLUMN - 1


_UNDERLINE_CLASSES = (LineClass.PROSE, LineClass.THEMATIC_BREAK, LineClass.LIST_MARKER)


def _apply_setext(lines: list[Line]) -> None:
    """Reclassify a paragraph followed by an ``===``/``---`` rule as a heading.

    A setext underline closes a paragraph, not a list. Without the container
    check `- a\n- b\n---` turned the whole list into a heading, inventing
    anchors and an `ambiguous-anchor` finding for text that is not a heading.
    """
    for index, line in enumerate(lines):
        if index == 0 or line.cls not in _UNDERLINE_CLASSES:
            continue
        if lines[index - 1].cls is not LineClass.PROSE:
            continue
        start = _paragraph_start(lines, index - 1)
        # An underline cannot be a lazy continuation line: without the `>` of
        # its paragraph it is one more line of that paragraph.
        if _line_depth(line) < _line_depth(lines[start]):
            continue
        if not _underlines(_split_quote(line)[1], _split_quote(lines[start])[1]):
            continue
        for heading in range(start, index + 1):
            lines[heading] = replace(
                lines[heading], cls=LineClass.HEADING, cont_prefix="", block=-1
            )


def _mark_managed(lines: list[Line], index: int) -> None:
    lines[index] = replace(lines[index], cls=LineClass.MANAGED, prefix="", cont_prefix="")


def _apply_managed(lines: list[Line]) -> None:
    """Reclassify mdd-managed export callouts and callout markers.

    These are matched on export and stripped before a push, so a reflow that
    reshaped one could push it into the page body.
    """
    for index, line in enumerate(lines):
        if line.cls not in (LineClass.PROSE, LineClass.BLOCK_QUOTE):
            continue
        quote, rest = _split_quote(line)
        if not quote:
            continue
        content = rest.strip(MD_SPACE)
        if _ALERT_MARKER.match(content):
            _mark_managed(lines, index)
            continue
        if not _MANAGED_CALLOUT.match(content):
            continue
        forward = index
        while forward < len(lines) and lines[forward].quote:
            _mark_managed(lines, forward)
            forward += 1


def _split_quote(line: Line) -> tuple[str, str]:
    """Split *line* into the block-quote markers the scan found and the remainder.

    The scan knows which quotes were open, so it may strip a ``>`` that
    :func:`_strip_quote` on the text alone would read as content.
    """
    return line.quote, line.text[len(line.quote) :]


def _line_depth(line: Line) -> int:
    """Return how many block quotes deep *line* is.

    A quote may open after a list marker, as in ``- > a``, where the scan
    leaves the ``>`` in the line's prefix rather than in its quote.
    """
    return max(_quote_depth(line.quote), _quote_depth(line.prefix))


def _continues_paragraph(depth: int, line: Line) -> bool:
    """True when prose *line* continues a paragraph *depth* block quotes deep.

    Paragraph continuation ignores indentation and tolerates a missing ``>``
    (CommonMark's lazy continuation), so an indented or lazy line belongs to
    the paragraph above it. Only a line that opens a block of its own starts a
    new one: a list or footnote marker the scan took as one, or a block quote
    deeper than the paragraph. The paragraph's depth is that of its first line, not of the line
    before: after a lazy line, a line with its ``>`` back still continues it.
    A bare list marker is never prose at all, so it cannot join one.
    """
    if _split_markers(line.prefix[len(line.quote) :]) is not None:
        return False
    return _line_depth(line) <= depth


def _assign_blocks(lines: list[Line]) -> None:
    """Group contiguous prose lines that belong to the same logical paragraph."""
    previous: Line | None = None
    depth = 0
    counter = 0
    for index, line in enumerate(lines):
        if line.cls is not LineClass.PROSE:
            previous = None
            continue
        if previous is not None and _continues_paragraph(depth, line):
            block = previous.block
        else:
            counter += 1
            block = counter
            depth = _line_depth(line)
        lines[index] = replace(line, block=block)
        previous = lines[index]


_UNMASKED_CLASSES = (LineClass.FRONTMATTER, LineClass.FENCED_CODE, LineClass.INDENTED_CODE)


def block_text(lines: Sequence[Line]) -> tuple[str, list[int]]:
    """Unwrap a prose block to one logical string, plus each line's start offset.

    Masking must run over this string rather than per line: a hard-wrapped
    paragraph can split a code span or a link across a soft break, and a
    per-line scan sees two unbalanced halves instead of one construct.
    """
    starts: list[int] = []
    parts: list[str] = []
    position = 0
    for line in lines:
        if parts:
            position += 1
        starts.append(position)
        content = line.text[len(line.prefix) :].rstrip(MD_SPACE)
        parts.append(content)
        position += len(content)
    return " ".join(parts), starts


@dataclass(frozen=True)
class _Bound:
    """Where one line of a block sits within the block's joined text."""

    index: int
    start: int
    length: int
    shift: int

    def clip(self, span: Span) -> Span | None:
        low, high = max(span.start, self.start), min(span.end, self.start + self.length)
        return Span(low + self.shift, high + self.shift, span.cls) if low < high else None

    def holds(self, position: int) -> bool:
        return self.start <= position < self.start + self.length


def _block_bounds(lines: Sequence[Line], indices: Sequence[int]) -> list[_Bound]:
    block = [lines[index] for index in indices]
    _, starts = block_text(block)
    return [
        _Bound(
            index=index,
            start=starts[offset],
            length=len(block[offset].content.rstrip(MD_SPACE)),
            shift=len(block[offset].prefix) - starts[offset],
        )
        for offset, index in enumerate(indices)
    ]


def _spread_masks(lines: list[Line], indices: Sequence[int]) -> None:
    """Scan one block's joined text and project the spans back onto its lines."""
    joined, _ = block_text([lines[index] for index in indices])
    result = scan(joined)
    for bound in _block_bounds(lines, indices):
        spans = [clipped for span in result.masks if (clipped := bound.clip(span)) is not None]
        links = [
            LinkRef(ref.start + bound.shift, ref.target)
            for ref in result.links
            if bound.holds(ref.start)
        ]
        lines[bound.index] = replace(lines[bound.index], masks=tuple(spans), links=tuple(links))


def _apply_masks(lines: list[Line]) -> None:
    """Mask inline constructs: per block for prose, per line for everything else."""
    blocks: dict[int, list[int]] = {}
    for index, line in enumerate(lines):
        if line.cls is LineClass.PROSE:
            blocks.setdefault(line.block, []).append(index)
        elif line.cls not in _UNMASKED_CLASSES:
            result = scan(line.text, start=len(line.prefix))
            lines[index] = replace(line, masks=result.masks, links=result.links)
    for indices in blocks.values():
        _spread_masks(lines, indices)


def classify(text: str) -> Classified | ClassifyError:
    """Classify *text* line by line, or explain why it cannot be classified."""
    if newline_style(text) is None:
        return ClassifyError(1, "file mixes line endings")
    raw_lines, newline, final_newline = split_lines(text)
    lines, error, state = _scan_blocks(raw_lines)
    if error is not None:
        return error
    _reclaim_code_blanks(lines)
    # Blocks twice: the setext pass needs to know where each paragraph starts,
    # and the headings it makes are paragraphs no longer.
    _assign_blocks(lines)
    _apply_setext(lines)
    _apply_managed(lines)
    _apply_divergent(lines, state.divergent_paragraphs, state.divergent_lines)
    _assign_blocks(lines)
    _apply_masks(lines)
    return Classified(lines=tuple(lines), newline=newline, final_newline=final_newline)
