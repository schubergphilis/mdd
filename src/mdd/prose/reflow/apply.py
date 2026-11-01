"""Per-block rewriting and the reflow findings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mdd.prose.classify import LineClass, block_text, join_lines
from mdd.prose.inline import mask_flags, scan
from mdd.prose.reflow.clauses import PackedLine, Unit, merge_block_starters, pack, split_units
from mdd.prose.reflow.sentences import segment
from mdd.prose.report import Finding, make_excerpt

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mdd.prose.classify import Classified, Line
    from mdd.prose.config import ProseConfig, ReflowConfig


#: A block prefix that opens a footnote definition, after any container prefix.
_FOOTNOTE_DEFINITION = re.compile(r"\[\^[^\]]*\]:[ \t]*$")


#: The run of indent and block-quote markers a line starts with.
_LEADING = re.compile(r"[ \t>]*")


def _join_block(lines: Sequence[Line]) -> tuple[str, list[bool], list[int]]:
    """Unwrap a block to one logical string, carrying the mask vector and line starts."""
    joined, starts = block_text(lines)
    return joined, mask_flags(len(joined), scan(joined).masks), starts


def _masked_break_before_tab(lines: Sequence[Line], flags: list[bool], starts: list[int]) -> bool:
    """True when a line break inside a masked span comes before a tab-indented line.

    A container can take only part of a tab's columns, and a renderer may keep
    the rest as spaces inside a code span. Moving that break, or rewriting the
    indent, changes the span's text.
    """
    for line, start in zip(lines[1:], starts[1:], strict=True):
        leading = _LEADING.match(line.text)
        if leading is not None and "\t" in leading.group() and flags[start - 1]:
            return True
    return False


def reflow_block(lines: Sequence[Line], config: ReflowConfig) -> list[str] | None:
    """Return *lines* reflowed, or ``None`` when the block must not be touched.

    A block carrying a Markdown hard line break is left alone: the two trailing
    spaces are load-bearing and joining the block would silently delete them.
    So is a block with a tab-indented line that starts inside a code span or
    another masked span.
    """
    if any(line.hard_break for line in lines):
        return None
    joined, flags, starts = _join_block(lines)
    if not joined.strip() or _masked_break_before_tab(lines, flags, starts):
        return None
    prefix = lines[0].prefix
    cont = lines[0].cont_prefix
    packed: list[PackedLine] = []
    previous_end = 0
    for sentence in segment(joined, flags, config):
        units = split_units(joined, flags, sentence.start, sentence.end)
        if units:
            # The whitespace between two sentences belongs to the next one's
            # first unit, so a merged-back line keeps it.
            gap = joined[previous_end : sentence.start] + units[0].gap
            units[0] = Unit(gap=gap, text=units[0].text)
        previous_end = sentence.end
        packed.extend(
            pack(
                units,
                width=config.width,
                min_line=config.min_line,
                first_indent=len(prefix) if not packed else len(cont),
                cont_indent=len(cont),
            )
        )
    definition = _FOOTNOTE_DEFINITION.search(prefix) is not None
    merged = merge_block_starters(packed, definition=definition)
    return [(prefix if index == 0 else cont) + text for index, text in enumerate(merged)]


@dataclass(frozen=True)
class Rewrite:
    """The reflowed file text, and which of the original lines it changed.

    ``changed`` holds the first line of every block that changed, and
    ``differing`` every original line that is not the same as the line in its
    position in the reflowed block.
    """

    text: str
    changed: tuple[int, ...]
    differing: tuple[int, ...] = ()


def _differing_lines(block: Sequence[Line], rewritten: Sequence[str]) -> list[int]:
    """The original lines of *block* that differ from the reflowed line in their position."""
    out = [
        line.number
        for index, line in enumerate(block)
        if index >= len(rewritten) or rewritten[index] != line.text
    ]
    # A changed block always differs somewhere; the guard keeps it reported.
    return out or [block[0].number]


def _block_span(lines: Sequence[Line], start: int) -> int:
    block = lines[start].block
    end = start
    while end < len(lines) and lines[end].cls is LineClass.PROSE and lines[end].block == block:
        end += 1
    return end


def reflow_text(classified: Classified, config: ReflowConfig) -> Rewrite:
    """Reflow every prose block in *classified*."""
    lines = classified.lines
    out: list[str] = []
    changed: list[int] = []
    differing: list[int] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.cls is not LineClass.PROSE or line.block < 0:
            out.append(line.text)
            index += 1
            continue
        end = _block_span(lines, index)
        block = lines[index:end]
        originals = [item.text for item in block]
        rewritten = reflow_block(block, config)
        if rewritten is None or rewritten == originals:
            out.extend(originals)
        else:
            out.extend(rewritten)
            changed.append(block[0].number)
            differing.extend(_differing_lines(block, rewritten))
        index = end
    text = join_lines(out, classified.newline, final_newline=classified.final_newline)
    return Rewrite(text=text, changed=tuple(changed), differing=tuple(differing))


def findings(
    path: Path, classified: Classified, config: ProseConfig, rewrite: Rewrite
) -> list[Finding]:
    """Report one finding per prose line that differs from its reflowed form."""
    severity = config.severity("reflow")
    by_number = {line.number: line for line in classified.lines}
    return [
        Finding(
            path=path,
            line=number,
            column=0,
            check="reflow",
            rule="reflow",
            message="prose line is not in semantic-line-break form",
            severity=severity,
            excerpt=make_excerpt(by_number[number].text, 0),
            fixable=True,
        )
        for number in rewrite.differing
    ]
