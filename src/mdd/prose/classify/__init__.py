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

from mdd.prose.classify.lines import (
    Classified,
    ClassifyError,
    Line,
    LineClass,
    join_lines,
    newline_style,
    split_lines,
)
from mdd.prose.classify.masks import apply_masks, block_text
from mdd.prose.classify.passes import (
    apply_divergent,
    apply_managed,
    apply_setext,
    assign_blocks,
    keep_list_blank_runs,
    reclaim_code_blanks,
)
from mdd.prose.classify.prefixes import MD_SPACE
from mdd.prose.classify.scan import scan_blocks

__all__ = [
    "MD_SPACE",
    "Classified",
    "ClassifyError",
    "Line",
    "LineClass",
    "block_text",
    "classify",
    "join_lines",
    "newline_style",
    "split_lines",
]


def classify(text: str) -> Classified | ClassifyError:
    """Classify *text* line by line, or explain why it cannot be classified."""
    if newline_style(text) is None:
        return ClassifyError(1, "file mixes line endings")
    raw_lines, newline, final_newline = split_lines(text)
    lines, error, state = scan_blocks(raw_lines)
    if error is not None:
        return error
    reclaim_code_blanks(lines)
    # Blocks twice: the setext pass needs to know where each paragraph starts,
    # and the headings it makes are paragraphs no longer.
    assign_blocks(lines)
    apply_setext(lines)
    apply_managed(lines)
    apply_divergent(lines, state.divergent_paragraphs, state.divergent_lines)
    keep_list_blank_runs(lines, state.list_blanks)
    assign_blocks(lines)
    apply_masks(lines)
    return Classified(lines=tuple(lines), newline=newline, final_newline=final_newline)
