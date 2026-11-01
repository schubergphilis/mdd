"""Clause-boundary detection and greedy clause packing.

Breaking at *every* comma is wrong and is not the behaviour: an ordinary
in-sentence list becomes one line per item, which is a worse diff than the hard
wrap it replaced. The algorithm is greedy packing to a soft width, so a short
sentence is one line and a long sentence becomes a few coherent lines.

The whitespace between two units is carried with them, so units packed onto
the same line are rejoined with the bytes that separated them. Only the
whitespace at a chosen break point is replaced, by the line break.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mdd.prose.classify import MD_SPACE
from mdd.prose.reflow.nesting import nested_flags

if TYPE_CHECKING:
    from collections.abc import Sequence

_BOUNDARY_MARKS = ",;:"


@dataclass(frozen=True)
class Unit:
    """One clause unit, and the whitespace that separated it from the one before."""

    gap: str
    text: str


@dataclass(frozen=True)
class PackedLine:
    """One generated line, and the whitespace that preceded it in the source."""

    gap: str
    text: str


_DASHES = "—–"


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


def _unit(text: str, cursor: int, end: int) -> Unit | None:
    """The unit in ``text[cursor:end]``, with its leading whitespace as the gap."""
    raw = text[cursor:end]
    body = raw.lstrip(MD_SPACE)
    stripped = body.rstrip(MD_SPACE)
    if not stripped:
        return None
    return Unit(gap=raw[: len(raw) - len(body)], text=stripped)


def split_units(text: str, masked: Sequence[bool], start: int, end: int) -> list[Unit]:
    """Split ``text[start:end]`` into clause units at top-level boundaries.

    A boundary is a ``,``, ``;``, ``:`` or a spaced em/en dash at bracket and
    quote depth zero and outside every masked span. The punctuation stays with
    the unit that precedes it.
    """
    nested = nested_flags(text, masked, start, end)
    units: list[Unit] = []
    cursor = start
    index = start
    while index < end:
        char = text[index]
        if masked[index] or nested[index - start]:
            index += 1
            continue
        if (char in _BOUNDARY_MARKS or _spaced_dash(text, index)) and _followed_by_space(
            text, index, end
        ):
            unit = _unit(text, cursor, index + 1)
            if unit is not None:
                units.append(unit)
            cursor = index + 1
        index += 1
    tail = _unit(text, cursor, end)
    if tail is not None:
        units.append(tail)
    return units


#: What a new line must not start with. Moving a sentence onto its own line can
#: put a ``>`` or a ``-`` in column one, which turns prose into a block quote or
#: a list item — a change of meaning, not of layout. The list errs wide: a
#: line merged back only costs a break.
_BLOCK_STARTER = re.compile(
    # Block quote, ATX heading, bullet and ordered list items.
    r">"
    r"|#{1,6}(?:\s|$)"
    r"|[-*+](?:\s|$)"
    r"|\d{1,9}[.)](?:\s|$)"
    # Thematic breaks in every spelling: three or more of one mark, spaced
    # or not. The `-` and `*` forms with a space are list markers above too.
    r"|(?:\*[ \t]*){3,}$"
    r"|(?:_[ \t]*){3,}$"
    r"|(?:-[ \t]*){3,}$"
    # Setext underlines, and anything shaped like a table delimiter row,
    # which would turn the line before into a heading or a table header.
    r"|=+\s*$"
    r"|[-:|][-:| \t]*$"
    # Fences, tables, math blocks, fenced divs, HTML blocks.
    r"|`{3,}"
    r"|~{3,}"
    r"|\|"
    r"|\$\$"
    r"|:{3,}"
    r"|<[A-Za-z!/?]"
    # Link and footnote definitions, whatever the label holds.
    r"|\[.*\]:"
    # A generated line starting with one of these classifies as a
    # `managed-region`, which silently exempts it and every following quoted
    # line from all checks. Reflow must not be able to manufacture one.
    r"|\*\*(?:Confluence|SharePoint) export\*\*"
    r"|\[!\w+\]"
)


def _must_join(out: Sequence[str], line: PackedLine, *, definition: bool) -> bool:
    """True when *line* may not start a line of its own after *out*.

    In a footnote definition the first line must hold more than one token.
    mdd's model has no footnotes and reads ``[^1]: Ibid.`` alone on a line as
    a link definition, which turns the indented lines below it into code. A
    line a break leaves behind ends in a clause mark or a terminator, never in
    a link title's closing quote, so any whitespace on it is enough.
    """
    if not out:
        return False
    if _BLOCK_STARTER.match(line.text):
        return True
    return definition and len(out) == 1 and not any(char in MD_SPACE for char in out[0])


def merge_block_starters(lines: Sequence[PackedLine], *, definition: bool = False) -> list[str]:
    """Join back any generated line that would start a new Markdown block.

    The line is rejoined with the whitespace that preceded it in the source.
    *definition* says the block is a footnote definition.
    """
    out: list[str] = []
    for line in lines:
        if _must_join(out, line, definition=definition):
            out[-1] = out[-1] + line.gap + line.text
        else:
            out.append(line.text)
    return out


def _tail_length(units: Sequence[Unit], index: int) -> int:
    return len(" ".join(unit.text for unit in units[index:]))


def pack(
    units: Sequence[Unit],
    *,
    width: int,
    min_line: int,
    first_indent: int,
    cont_indent: int,
) -> list[PackedLine]:
    """Greedily pack *units* into lines that stay within the soft *width*.

    A unit longer than the width is emitted on its own line rather than broken
    mid-clause: breaking mid-clause to satisfy a column count would reintroduce
    exactly the hard-wrap diff churn this feature exists to remove.

    A break is not taken when it would leave a fragment shorter than
    *min_line* on either side: the line it ends, or the rest of the sentence.

    Every length is measured as though each gap were one space. A gap at a
    break point becomes a single space when the next run joins the lines again,
    so measuring the real gap would let a second run pack differently from the
    first, and the reflow would not be idempotent.
    """
    if not units:
        return []
    lines: list[PackedLine] = []
    gap, text = units[0].gap, units[0].text
    measured = len(text)
    for index in range(1, len(units)):
        unit = units[index]
        indent = first_indent if not lines else cont_indent
        fits = indent + measured + 1 + len(unit.text) <= width
        short_head = measured < min_line
        short_tail = _tail_length(units, index) < min_line
        if fits or short_head or short_tail:
            text += unit.gap + unit.text
            measured += 1 + len(unit.text)
        else:
            lines.append(PackedLine(gap, text))
            gap, text = unit.gap, unit.text
            measured = len(text)
    lines.append(PackedLine(gap, text))
    return lines
