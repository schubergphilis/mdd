"""Clause-boundary detection and greedy clause packing.

Breaking at *every* comma is wrong and is not the behaviour: an ordinary
in-sentence list becomes one line per item, which is a worse diff than the hard
wrap it replaced. The algorithm is greedy packing to a soft width, so a short
sentence is one line and a long sentence becomes a few coherent lines.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from mdd.prose.classify import MD_SPACE

if TYPE_CHECKING:
    from collections.abc import Sequence

_BOUNDARY_MARKS = ",;:"
_DASHES = "—–"
_OPENERS = "([{"
_CLOSERS = ")]}"
_QUOTES = '"“”«»'


def _followed_by_space(text: str, index: int, end: int) -> bool:
    """True when a boundary candidate at *index* is followed by whitespace or the end.

    Load-bearing: a mark with no space after it is inside a token, not between
    clauses. Splitting ``**Status:**`` at the colon and rejoining the halves
    with a space corrupts the emphasis.
    """
    return index + 1 >= end or text[index + 1] in " \t"


def _spaced_dash(text: str, index: int) -> bool:
    if text[index] not in _DASHES:
        return False
    return index > 0 and text[index - 1] in " \t"


def split_units(text: str, masked: Sequence[bool], start: int, end: int) -> list[str]:
    """Split ``text[start:end]`` into clause units at top-level boundaries.

    A boundary is a ``,``, ``;``, ``:`` or a spaced em/en dash at bracket and
    quote depth zero and outside every masked span. The punctuation stays with
    the unit that precedes it.
    """
    units: list[str] = []
    depth = 0
    in_quote = False
    cursor = start
    index = start
    while index < end:
        char = text[index]
        if masked[index]:
            index += 1
            continue
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            depth = max(0, depth - 1)
        elif char in _QUOTES:
            in_quote = not in_quote
        elif (
            depth == 0
            and not in_quote
            and (char in _BOUNDARY_MARKS or _spaced_dash(text, index))
            and _followed_by_space(text, index, end)
        ):
            unit = text[cursor : index + 1].strip(MD_SPACE)
            if unit:
                units.append(unit)
            cursor = index + 1
        index += 1
    tail = text[cursor:end].strip(MD_SPACE)
    if tail:
        units.append(tail)
    return units


#: What a new line must not start with. Moving a sentence onto its own line can
#: put a ``>`` or a ``-`` in column one, which turns prose into a block quote or
#: a list item — a change of meaning, not of layout.
_BLOCK_STARTER = re.compile(
    r">"
    r"|#{1,6}(?:\s|$)"
    r"|[-*+](?:\s|$)"
    r"|\d{1,9}[.)](?:\s|$)"
    r"|`{3,}"
    r"|~{3,}"
    r"|\|"
    r"|=+\s*$"
    r"|-{2,}\s*$"
    r"|\[[^\]]*\]:"
    r"|\$\$"
    r"|<[A-Za-z!/?]"
    r"|:{3,}"
    # A generated line starting with one of these classifies as a
    # `managed-region`, which silently exempts it and every following quoted
    # line from all checks. Reflow must not be able to manufacture one.
    r"|\*\*(?:Confluence|SharePoint) export\*\*"
    r"|\[!\w+\]"
)


def merge_block_starters(lines: Sequence[str]) -> list[str]:
    """Join back any generated line that would start a new Markdown block."""
    out: list[str] = []
    for line in lines:
        if out and _BLOCK_STARTER.match(line):
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return out


def _tail_length(units: Sequence[str], index: int) -> int:
    return len(" ".join(units[index:]))


def pack(
    units: Sequence[str],
    *,
    width: int,
    min_line: int,
    first_indent: int,
    cont_indent: int,
) -> list[str]:
    """Greedily pack *units* into lines that stay within the soft *width*.

    A unit longer than the width is emitted on its own line rather than broken
    mid-clause: breaking mid-clause to satisfy a column count would reintroduce
    exactly the hard-wrap diff churn this feature exists to remove.
    """
    if not units:
        return []
    lines: list[str] = []
    current = units[0]
    for index in range(1, len(units)):
        unit = units[index]
        indent = first_indent if not lines else cont_indent
        candidate = f"{current} {unit}"
        fits = indent + len(candidate) <= width
        keeps_tail = _tail_length(units, index) < min_line
        if fits or keeps_tail:
            current = candidate
        else:
            lines.append(current)
            current = unit
    lines.append(current)
    return lines
