"""The block text a check reads, and spreading inline masks across a block's lines."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from mdd.prose.classify.lines import Line, LineClass
from mdd.prose.classify.prefixes import MD_SPACE
from mdd.prose.inline import LinkRef, Span, scan

if TYPE_CHECKING:
    from collections.abc import Sequence

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


def apply_masks(lines: list[Line]) -> None:
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
