"""Passes over the scanned lines: setext headings, managed callouts, divergent
paragraphs, list blank runs and paragraph blocks.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from mdd.prose.classify.lines import Line, LineClass
from mdd.prose.classify.prefixes import (
    INDENTED_CODE_COLUMN,
    MD_SPACE,
    SETEXT,
    columns,
    indent_columns,
    quote_depth,
    split_markers,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_ALERT_MARKER = re.compile(r"^\[!\w+\]$")
_MANAGED_CALLOUT = re.compile(r"^\*\*(?:Confluence|SharePoint) export\*\*")


def _opens_on_colons(line: Line) -> bool:
    """True when the content of prose *line* starts with a run of three or more colons."""
    return line.text[len(line.prefix) :].lstrip(MD_SPACE).startswith(":::")


def apply_divergent(
    lines: list[Line], divergent_paragraphs: set[int], lines_only: set[int]
) -> None:
    """Make the prose lines renderers disagree on, and their paragraphs, divergent.

    So is every paragraph with a line that opens on a colon run. mdd's renderer
    reads one with a name it does not know as text, but to Pandoc and Quarto it
    is a div marker, and joining it into the paragraph breaks the div.
    """
    blocks = {
        line.block
        for line in lines
        if line.cls is LineClass.PROSE
        and (line.number in divergent_paragraphs or _opens_on_colons(line))
    }
    for index, line in enumerate(lines):
        if line.cls is not LineClass.PROSE:
            continue
        if line.block in blocks or line.number in lines_only:
            lines[index] = replace(line, cls=LineClass.DIVERGENT, block=-1, cont_prefix="")


def keep_list_blank_runs(lines: list[Line], list_blanks: set[int]) -> None:
    """Make a run of blank lines in a list item divergent when an indented line follows.

    Whether such a line is still in the item can depend on how many blank
    lines come before it: in CommonMark an item that starts with a link
    definition ends at two of them and not at one, where markdown-it reads
    both the same. Collapsing the run is then not safe, so it is kept.
    """
    run: list[int] = []
    for index, line in enumerate([*lines, None]):
        if line is not None and line.cls is LineClass.BLANK:
            run.append(index)
            continue
        keep = (
            len(run) > 1
            and line is not None
            and lines[run[0]].number in list_blanks
            and indent_columns(line.text[len(line.quote) :]) > 0
        )
        if keep:
            for blank in run:
                lines[blank] = replace(lines[blank], cls=LineClass.DIVERGENT)
        run = []


def reclaim_code_blanks(lines: list[Line]) -> None:
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

    Reads the block numbers :func:`assign_blocks` gave the prose lines.
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
    if not SETEXT.match(underline.lstrip(MD_SPACE)):
        return False
    indent = indent_columns(underline)
    split = split_markers(first)
    if split is None:
        return indent <= max(INDENTED_CODE_COLUMN - 1, indent_columns(first) + 3)
    if ">" in split[0]:
        # A block quote inside the item: where its underline may sit is not
        # worth working out, and a heading is the safe guess.
        return True
    column = columns(split[0])
    return column <= indent <= column + INDENTED_CODE_COLUMN - 1


_UNDERLINE_CLASSES = (LineClass.PROSE, LineClass.THEMATIC_BREAK, LineClass.LIST_MARKER)


def apply_setext(lines: list[Line]) -> None:
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


def apply_managed(lines: list[Line]) -> None:
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
    :func:`strip_quote` on the text alone would read as content.
    """
    return line.quote, line.text[len(line.quote) :]


def _line_depth(line: Line) -> int:
    """Return how many block quotes deep *line* is.

    A quote may open after a list marker, as in ``- > a``, where the scan
    leaves the ``>`` in the line's prefix rather than in its quote.
    """
    return max(quote_depth(line.quote), quote_depth(line.prefix))


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
    if split_markers(line.prefix[len(line.quote) :]) is not None:
        return False
    return _line_depth(line) <= depth


def assign_blocks(lines: list[Line]) -> None:
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
