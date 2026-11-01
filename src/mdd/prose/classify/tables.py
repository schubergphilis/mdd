"""Tracking pipe tables, whose rows must stay in the table's container."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from mdd.prose.classify.lines import Line, LineClass
from mdd.prose.classify.prefixes import (
    INDENTED_CODE_COLUMN,
    indent_columns,
    quote_depth,
    split_markers,
)
from mdd.prose.classify.state import LIST, State, container_column

if TYPE_CHECKING:
    from collections.abc import Sequence

#: A table's delimiter row. One column is enough; the caller also requires a pipe.
_DELIM_ROW = re.compile(r"^[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")


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
        and quote_depth(quote) == depth
        and LIST.match(rest) is None
        and indent_columns(rest) >= column
    )


def _opens_table(rest: str, out: Sequence[Line]) -> bool:
    """True when *rest* is a delimiter row under a header row."""
    if not out or not _DELIM_ROW.match(rest) or "|" not in rest:
        return False
    header = out[-1]
    return header.cls is LineClass.PROSE and "|" in header.text


def _open_table(quote: str, rest: str, out: list[Line], state: State) -> None:
    """Record the table *rest* opens, and close the list items it shows never opened.

    markdown-it tries a table before a new list, so a header row that starts
    a list is a table in the enclosing container, the marker one of its
    cells, unless the delimiter row is too far indented for that. A header
    row that is the next item of an open list is read by the list instead,
    and its table is in the item.
    """
    header_rest = out[-1].text[len(out[-1].quote) :]
    header_indent = indent_columns(header_rest)
    delimiter_indent = indent_columns(rest)
    outer = container_column(header_indent, state)
    starts_list = not any(column > header_indent for column in state.cols_before_previous)
    if (
        starts_list
        and split_markers(header_rest) is not None
        and delimiter_indent - outer < INDENTED_CODE_COLUMN
    ):
        while state.list_cols and state.list_cols[-1] > header_indent:
            _ = state.list_cols.pop()
    while state.list_cols and state.list_cols[-1] > delimiter_indent:
        _ = state.list_cols.pop()
    state.table = (quote_depth(quote), container_column(delimiter_indent, state))
    out[-1] = _table_line(out[-1])


def track_table(line: Line, quote: str, rest: str, out: list[Line], state: State) -> Line:
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
