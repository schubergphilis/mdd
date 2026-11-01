"""The block scanner's mutable state, and tracking the open list items in it."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mdd.prose.classify.lines import ClassifyError, Line, LineClass
from mdd.prose.classify.prefixes import (
    INDENTED_CODE_COLUMN,
    MD_SPACE,
    TBREAK,
    columns,
    drop_columns,
    gap_is_code,
    indent_columns,
    list_content_column,
)

LIST = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])([ \t]+)(?=\S)")
_LIST_BARE = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])[ \t]*$")
FOOTNOTE_DEF = re.compile(r"^([ \t]*\[\^[^\]\s]+\]:[ \t]*)(?=\S)")


@dataclass
class State:
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
    #: The block-quote depth and list item content column the open HTML block
    #: is in. It ends where that container ends.
    html_quote_depth: int = 0
    html_container: int = 0
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
    #: The closing marker and block-quote depth of a fenced div opened in a
    #: block quote, while the quote it was opened in is still open.
    quote_div: tuple[str, int] | None = None
    #: The line before was blank and inside that quote, so a line without
    #: its ``>`` ends the quote rather than continuing it.
    quote_div_after_blank: bool = False
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
    #: Blank lines read while a list item was open.
    list_blanks: set[int] = field(default_factory=set)


def close_items(rest: str, state: State) -> None:
    """Close every open list item that *rest*, starting a block, is indented less than.

    Called for every fresh line that starts a block, not only the ones that end
    up as prose. A heading, a fence or a thematic break at column zero ends the
    list just as a paragraph does, and leaving the content column set after one
    raised the indented-code floor so a genuine four-space code block read as
    prose, and the fixers then rewrote its interior.
    """
    if not rest.strip(MD_SPACE):
        return
    indent = indent_columns(rest)
    while state.list_cols and state.list_cols[-1] > indent:
        _ = state.list_cols.pop()


def container_column(indent: int, state: State) -> int:
    """Return the content column of the innermost open item a line at *indent* is in."""
    return max((column for column in state.list_cols if column <= indent), default=0)


def _interrupts_paragraph(rest: str) -> bool:
    """True when the list item on *rest* may interrupt a paragraph.

    Only an item with content may, and of ordered items only one numbered 1. A
    bare `-` under a paragraph is a setext underline, and `10. x` continues it.
    """
    if FOOTNOTE_DEF.match(rest):
        # markdown-it's footnote rule may; cmark-gfm's may not, and the scan
        # makes both paragraphs divergent.
        return True
    item = LIST.match(rest)
    if item is None:
        return False
    number = item.group(2)[:-1]
    return not number or number == "1"


def continues_paragraph_text(rest: str, state: State) -> bool:
    """True when a list marker on *rest* is paragraph text rather than a new item.

    A marker that cannot interrupt a paragraph continues it, unless it sits
    left of the paragraph's list item: then it starts a sibling item. A colon
    run kept as a possible div closer may be paragraph text too, so an item
    after one may be continuing a paragraph. Opening fewer
    items is the safe guess: it only lowers the indented-code floor.
    """
    paragraph = state.in_paragraph or state.after_div_marker
    innermost = state.list_cols[-1] if state.list_cols else 0
    return paragraph and not _interrupts_paragraph(rest) and indent_columns(rest) >= innermost


def _open_items(rest: str, state: State) -> bool:
    """Open one list item per marker *rest* starts with; say whether there was one.

    Markers nest, as in ``- 1. a``, and each opens an item one level deeper. A
    run like ``* * *`` after the first marker is a thematic break, not more
    items. A marker after a gap wide enough to start indented code is code,
    not another item.
    """
    consumed = 0
    while (item := LIST.match(rest[consumed:]) or _LIST_BARE.match(rest[consumed:])) is not None:
        if consumed and TBREAK.match(rest[consumed:]):
            break
        if not consumed:
            close_items(rest, state)
        gap = item.group(3) if item.re is LIST else ""
        column = list_content_column(item.group(1), item.group(2), gap)
        state.list_cols.append(columns(rest[:consumed]) + column)
        consumed += item.end()
        if gap_is_code(rest[:consumed], gap):
            break
    return consumed > 0


def track_list(rest: str, state: State) -> None:
    """Open the list items *rest* starts, or close the ones it ends.

    A lazy paragraph continuation is less indented than its item and still
    belongs to it, so a line inside a paragraph closes nothing.
    """
    if continues_paragraph_text(rest, state):
        if not state.in_paragraph:
            close_items(rest, state)
        return
    if not _open_items(rest, state) and not state.in_paragraph:
        close_items(rest, state)


def is_indented_code(rest: str, state: State) -> bool:
    """True when *rest* belongs to an indented code block.

    An indented code block *opens* anywhere except inside a paragraph, but it
    *continues* for as long as the indent holds. Requiring a preceding blank on
    every line classified only the block's first line as code and handed the
    rest to the rewriters as prose; requiring one before the first line did the
    same to a code block straight after a heading.
    """
    if state.in_paragraph and not state.in_indented_code:
        return False
    indent = indent_columns(rest)
    return indent >= INDENTED_CODE_COLUMN + container_column(indent, state)


def container_content(rest: str, state: State) -> str:
    """Return *rest* as the open list item sees it, without the item's indent.

    A block opener may be indented at most three columns *within its
    container*. Measuring from the margin instead called a heading, maths or an
    HTML block at a list item's content column prose. A line indented less
    than the content column is outside the item and is measured as it stands.
    """
    column = container_column(indent_columns(rest), state)
    return drop_columns(rest, column) if column else rest


def set_block_container(opened: Line, indent: int, state: State) -> None:
    """Record the list item a fence or an HTML block opened at *indent* is in."""
    if opened.cls is LineClass.FENCED_CODE:
        state.fence_indent = indent
        state.fence_container = container_column(indent, state)
    elif opened.cls is LineClass.HTML_BLOCK:
        state.html_container = container_column(indent, state)
