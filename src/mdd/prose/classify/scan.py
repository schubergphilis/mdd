"""The line-by-line block scan, and the quote and div containers it tracks."""

from __future__ import annotations

import re
from dataclasses import replace

from mdd.markdown.ir.callouts import div_opener
from mdd.prose.classify.blocks import (
    DIV_CLOSER,
    HTML_BLOCK,
    close_div,
    continuation,
    link_definition,
    marker_line,
    open_block,
    single_line_class,
)
from mdd.prose.classify.lines import ClassifyError, Line, LineClass
from mdd.prose.classify.prefixes import (
    BQ,
    INDENTED_CODE_COLUMN,
    MD_SPACE,
    ONE_QUOTE,
    SETEXT,
    columns,
    indent_bytes,
    indent_columns,
    prose_line,
    quote_depth,
    split_markers,
    strip_quote,
)
from mdd.prose.classify.state import (
    FOOTNOTE_DEF,
    LIST,
    State,
    close_items,
    container_column,
    container_content,
    continues_paragraph_text,
    is_indented_code,
    set_block_container,
    track_list,
)
from mdd.prose.classify.tables import track_table

_BQ_ANY_INDENT = re.compile(r"(?:[ \t]*>[ \t]?)+")
_BYTE_ORDER_MARK = "\ufeff"

#: How deep a line's containers may nest, counting a block quote as one level
#: and a list item as two, as markdown-it does. markdown-it stops parsing at
#: twenty and drops what lies below unseen, so neither it nor the write gate
#: can vouch for an edit there. Two short of that, as the list model guesses.
_MAX_NESTING = 18


def _classify_fresh(number: int, raw: str, quote: str, rest: str, state: State) -> Line:
    """Classify a line that is not inside any open multi-line construct."""
    # Indented code is tested first: its contents are literal, so a line inside
    # it that happens to read as `<!--` or a fence must not open a construct.
    if is_indented_code(rest, state):
        return Line(number, raw, LineClass.INDENTED_CODE)
    inner = container_content(rest, state)
    opened = close_div(number, raw, quote, rest, state) or open_block(
        number, raw, quote, inner, state
    )
    if opened is not None:
        close_items(rest, state)
        set_block_container(opened, indent_columns(rest), state)
        return opened
    # A one-line block is looked for at any indent that is not code. Which list
    # item a line sits in is a guess, and a wrong guess must not hide a heading
    # or a rule; calling an indented paragraph line one only splits the
    # paragraph, and the writers leave the line alone.
    single = single_line_class(rest.lstrip(MD_SPACE))
    # A link definition cannot interrupt a paragraph: it is one more line of it.
    if single is LineClass.LINK_DEF and state.in_paragraph:
        single = None
    if single is not None:
        close_items(rest, state)
        return Line(number, raw, single, prefix=quote)
    # A marker that cannot interrupt the paragraph above it, such as `5.` or
    # `10. a`, is paragraph text, and so is the rest of its line.
    text_marker = state.in_paragraph and continues_paragraph_text(rest, state)
    track_list(rest, state)
    if not rest.strip(MD_SPACE):
        return Line(number, raw, LineClass.BLOCK_QUOTE if quote else LineClass.BLANK)
    if text_marker:
        return prose_line(number, raw, quote, rest, markers=False)
    return marker_line(number, raw, quote, rest, state) or prose_line(number, raw, quote, rest)


def _track_list_div(line: Line, rest: str, state: State) -> None:
    """Fail closed on a fenced div in a list item with a line outside the item.

    The fenced-div renderer looks for its closing marker past the end of the
    list item, and silently drops every line between the first one indented
    less than the item and that marker. Such a line is not prose, nor anything
    else the classifier has a class for, so the file is refused instead.
    """
    content = rest.strip(MD_SPACE)
    if state.list_div is not None:
        dedented = bool(content) and indent_columns(rest) < state.list_div_column
        if line.cls is LineClass.DIV_MARKER and content == state.list_div:
            state.list_div = None
        elif dedented and state.dropped is None:
            state.dropped = ClassifyError(
                line.number, "a fenced div in a list item drops a less-indented line"
            )
        return
    if line.cls is not LineClass.DIV_MARKER:
        return
    split = split_markers(rest)
    if split is None:
        indent, opener = indent_columns(rest), div_opener(rest.lstrip(MD_SPACE))
    else:
        indent, opener = columns(split[0]), div_opener(split[2].lstrip(MD_SPACE))
        if opener is not None and "[^" in split[0] and state.dropped is None:
            # The footnote rule and the fenced-div rule disagree on where the
            # div ends, and the renderer drops the lines in between.
            state.dropped = ClassifyError(
                line.number, "a fenced div opened on a footnote line may drop lines"
            )
            return
    column = container_column(indent, state)
    if opener is not None and column:
        state.list_div = opener
        state.list_div_column = column


def _track_quote_div(line: Line, quote: str, rest: str, open_paragraph: bool, state: State) -> None:
    """Fail closed on a fenced div in a block quote with a line outside the quote.

    markdown-it takes a line without the quote's ``>`` into the quote, but the
    fenced-div renderer drops it unless it continues an open paragraph. A
    line that would instead end the quote, such as a heading, is refused too:
    telling the two apart is not worth the risk. A blank line ends the quote,
    and the div with it, as does any line without the ``>`` after a blank one.
    """
    depth = quote_depth(quote)
    blank = not rest.strip(MD_SPACE)
    if state.quote_div is None:
        opener = div_opener(rest.lstrip(MD_SPACE))
        if line.cls is LineClass.DIV_MARKER and depth and opener is not None:
            state.quote_div = (opener, depth)
            state.quote_div_after_blank = False
        return
    fence, div_depth = state.quote_div
    closer = DIV_CLOSER.match(rest)
    if line.cls is LineClass.DIV_MARKER and closer is not None and closer.group(1) == fence:
        state.quote_div = None
    elif depth >= div_depth:
        state.quote_div_after_blank = blank
    elif blank or state.quote_div_after_blank:
        state.quote_div = None
    elif not (open_paragraph and line.cls is LineClass.PROSE) and state.dropped is None:
        state.dropped = ClassifyError(
            line.number, "a fenced div in a block quote drops a line outside it"
        )


def _strip_open_quote(raw: str, quote: str, rest: str, state: State) -> tuple[str, str]:
    """Strip the markers of the block quotes the line before left open, at any indent.

    markdown-it continues an open block quote on a ``>`` however far it is
    indented, while a new one may sit at most three columns in. Read as
    paragraph text, a tab-indented quote line handed the fence it opened to
    the fixers.
    """
    if quote_depth(quote) >= state.open_quotes:
        return quote, rest
    end = 0
    for _ in range(state.open_quotes):
        marker = ONE_QUOTE.match(raw, end)
        if marker is None:
            break
        end = marker.end()
    nested = BQ.match(raw, end)
    if nested is not None:
        end = nested.end()
    return raw[:end], raw[end:]


def _open_quotes_after(line: Line, quote: str, rest: str, state: State) -> int:
    """Return how many block quotes are open after *line*.

    A line without a ``>`` ends every open quote, unless it continues the
    paragraph inside one. A blank line never does, and a list item or footnote
    starts a block of its own.
    """
    depth = quote_depth(quote)
    if depth:
        return depth
    lazy = line.cls is LineClass.PROSE and state.in_paragraph
    if lazy and not (LIST.match(rest) or FOOTNOTE_DEF.match(rest)):
        return state.open_quotes
    return 0


def _strip_quote_in_item(quote: str, rest: str, state: State) -> tuple[str, str]:
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


def _in_literal_block(rest: str, state: State) -> bool:
    """True when *rest* is inside a construct whose lines are literal text."""
    return (
        state.in_frontmatter
        or state.in_comment
        or state.in_math
        or state.in_html_block
        or (state.fence is None and is_indented_code(rest, state))
    )


def scan_blocks(raw_lines: list[str]) -> tuple[list[Line], ClassifyError | None, State]:
    """Run the block-level state machine over *raw_lines*."""
    state = State()
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
        if number == 1 and raw.startswith(_BYTE_ORDER_MARK):
            # cmark-gfm skips the mark and markdown-it does not. Classified
            # without it, a fence or a heading on the first line is seen, and
            # the mark is kept as prefix so no writer moves it.
            line = _scan_line(number, raw[1:], out, state)
            out.append(replace(line, text=raw, prefix=_BYTE_ORDER_MARK + line.prefix))
            continue
        out.append(_scan_line(number, raw, out, state))
    return out, _unclosed(state), state


def _scan_line(number: int, raw: str, out: list[Line], state: State) -> Line:
    """Classify one line, given the lines before it and the scan state they left."""
    state.cols_before_previous = state.cols_before_line
    state.cols_before_line = list(state.list_cols)
    plain_quote, plain_rest = strip_quote(raw)
    quote, rest = _strip_open_quote(raw, plain_quote, plain_rest, state)
    deep_marker = len(quote) > len(plain_quote) and _deep_quote_marker(quote, state)
    if not _in_literal_block(rest, state):
        quote, rest = _strip_quote_in_item(quote, rest, state)
    deep_lazy = _deep_lazy_line(quote, rest, state)
    lazy_tag = _lazy_line(quote, rest, state) and HTML_BLOCK.match(rest) is not None
    footnote_interrupts = state.in_paragraph and FOOTNOTE_DEF.match(rest) is not None
    open_paragraph = state.in_paragraph
    # A deeper block quote opens a new container, and no paragraph is open
    # inside it yet. A shallower one is a lazy continuation.
    if quote_depth(quote) > state.paragraph_depth:
        state.in_paragraph = False
    line = continuation(number, raw, quote, rest, state) or _classify_fresh(
        number, raw, quote, rest, state
    )
    line = link_definition(line, rest, state)
    line = track_table(line, quote, rest, out, state)
    if line.cls is LineClass.PROSE and deep_marker:
        state.divergent_paragraphs.add(number)
    if line.cls is LineClass.PROSE and deep_lazy:
        state.divergent_lines.update((number - 1, number))
    if line.cls is LineClass.PROSE and (lazy_tag or footnote_interrupts):
        state.divergent_paragraphs.update((number - 1, number))
    _track_list_div(line, rest, state)
    _track_quote_div(line, quote, rest, open_paragraph, state)
    _track_nesting(number, quote, state)
    line = replace(line, quote=quote)
    _track_containers(line, quote, state)
    _after_line(line, quote, rest, state)
    return line


def _track_containers(line: Line, quote: str, state: State) -> None:
    """Note the blank lines in list items, and the item a new block quote opens in."""
    if line.cls is LineClass.BLANK and state.list_cols:
        state.list_blanks.add(line.number)
    if not state.open_quotes and quote:
        column = indent_columns(quote)
        state.quote_base = max((c for c in state.cols_before_line if c <= column), default=0)


def _deep_quote_marker(quote: str, state: State) -> bool:
    """True when a ``>`` in *quote* sits four or more columns past its container.

    markdown-it continues an open block quote on such a marker; CommonMark
    reads the line as indented code, or as paragraph text with a literal
    ``>``. The first marker is measured from the content column of the list
    item the quote started in, the others from the end of the marker before.
    """
    column = 0
    position = 0
    first = True
    while (marker := ONE_QUOTE.match(quote, position)) is not None and marker.end() > position:
        indent = indent_bytes(quote[position:])
        start = columns(indent, column)
        base = state.quote_base if first else column
        if start - base >= INDENTED_CODE_COLUMN:
            return True
        column = columns(quote[position + len(indent) : marker.end()], start)
        position = marker.end()
        first = False
    return False


def _lazy_line(quote: str, rest: str, state: State) -> bool:
    """True when *rest* may be a lazy continuation line of a quoted paragraph."""
    if not state.in_paragraph or quote_depth(quote) >= state.paragraph_depth:
        return False
    return bool(rest.strip(MD_SPACE))


def _deep_lazy_line(quote: str, rest: str, state: State) -> bool:
    """True when *rest* is a lazy line, indented four or more, of a quoted paragraph.

    markdown-it may end the paragraph there and start indented code, where
    CommonMark reads one more paragraph line, so a hard break at the end of
    the line above means something only to CommonMark.
    """
    if not _lazy_line(quote, rest, state):
        return False
    indent = indent_columns(rest)
    return indent - container_column(indent, state) >= INDENTED_CODE_COLUMN


def _track_nesting(number: int, quote: str, state: State) -> None:
    """Fail closed on a line nested deeper than markdown-it parses."""
    depth = quote_depth(quote) + 2 * len(state.list_cols)
    if depth >= _MAX_NESTING and state.dropped is None:
        state.dropped = ClassifyError(number, "the document nests too deeply to check")


def _after_line(line: Line, quote: str, rest: str, state: State) -> None:
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
        line.cls is LineClass.PROSE and not (state.in_paragraph and SETEXT.match(rest))
    )
    if line.cls is LineClass.PROSE:
        state.paragraph_depth = quote_depth(quote)
    state.after_div_marker = line.cls is LineClass.DIV_MARKER
    # A blank line does not end an indented code block — it is content inside
    # one — so the flag survives a blank and only a shallower non-blank line
    # clears it.
    if not blank:
        state.in_indented_code = line.cls is LineClass.INDENTED_CODE


def _unclosed(state: State) -> ClassifyError | None:
    """Return why the file cannot be classified once every line has been read."""
    if state.in_frontmatter:
        return ClassifyError(state.open_at, "frontmatter block never closes")
    if state.fence is not None:
        return ClassifyError(state.open_at, "fenced code block never closes")
    if state.in_comment:
        return ClassifyError(state.open_at, "HTML comment never closes")
    if state.in_math:
        return ClassifyError(state.open_at, "math block never closes")
    # An HTML block still open here is not an error: one that waits for a
    # closing marker, such as `<pre>`, runs to the end of the document, and
    # every line of it has been classified as such.
    return state.dropped
