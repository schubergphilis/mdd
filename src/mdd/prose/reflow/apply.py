"""Per-block rewriting, the equivalence gate, and the reflow findings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mdd.markdown.ir import parse_markdown, render_markdown
from mdd.prose.classify import ClassifyError, LineClass, block_text, classify, join_lines
from mdd.prose.inline import mask_flags, scan
from mdd.prose.reflow.clauses import merge_block_starters, pack, split_units
from mdd.prose.reflow.sentences import segment
from mdd.prose.report import Finding, make_excerpt
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mdd.prose.classify import Classified, Line
    from mdd.prose.config import ProseConfig, ReflowConfig

log = get_logger(__name__)


def _join_block(lines: Sequence[Line]) -> tuple[str, list[bool]]:
    """Unwrap a block to one logical string, carrying the mask vector with it."""
    joined, _ = block_text(lines)
    return joined, mask_flags(len(joined), scan(joined).masks)


def reflow_block(lines: Sequence[Line], config: ReflowConfig) -> list[str] | None:
    """Return *lines* reflowed, or ``None`` when the block must not be touched.

    A block carrying a Markdown hard line break is left alone: the two trailing
    spaces are load-bearing and joining the block would silently delete them.
    """
    if any(line.hard_break for line in lines):
        return None
    joined, flags = _join_block(lines)
    if not joined.strip():
        return None
    prefix = lines[0].prefix
    cont = lines[0].cont_prefix
    packed: list[str] = []
    for sentence in segment(joined, flags, config):
        units = split_units(joined, flags, sentence.start, sentence.end)
        packed.extend(
            pack(
                units,
                width=config.width,
                min_line=config.min_line,
                first_indent=len(prefix) if not packed else len(cont),
                cont_indent=len(cont),
            )
        )
    merged = merge_block_starters(packed)
    return [(prefix if index == 0 else cont) + text for index, text in enumerate(merged)]


@dataclass(frozen=True)
class Rewrite:
    """The reflowed file text, and the first line of every block that changed."""

    text: str
    changed: tuple[int, ...]


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
        index = end
    text = join_lines(out, classified.newline, final_newline=classified.final_newline)
    return Rewrite(text=text, changed=tuple(changed))


def canonical(text: str) -> str | None:
    """Return *text* parsed, normalised and re-rendered, or ``None`` if it will not parse."""
    try:
        return render_markdown(parse_markdown(text))
    except Exception:  # any parse failure means "cannot prove equivalence"
        log.debug("reflow equivalence: markdown did not parse", exc_info=True)
        return None


def _block_shape(text: str) -> list[str] | None:
    """The sequence of non-prose line classes, or ``None`` if *text* will not classify."""
    result = classify(text)
    if isinstance(result, ClassifyError):
        return None
    return [line.cls.value for line in result.lines if line.cls is not LineClass.PROSE]


def structurally_stable(before: str, after: str) -> bool:
    """True when reflow changed only prose lines.

    Reflow copies every non-prose line verbatim, so the sequence of non-prose
    classes must come out identical. If it did not, a *generated* line now reads
    as a block — a fence, a heading, a managed region — and the document means
    something different even when it happens to render the same.

    This catches what the render comparison cannot. A leading no-break space is
    invisible to the IR parser, so `\xa0``` ` reflowed into a real fence compared
    equal while leaving a file that no longer classifies at all.
    """
    left = _block_shape(before)
    right = _block_shape(after)
    return left is not None and right is not None and left == right


def equivalent(before: str, after: str) -> bool:
    """True when reflowing did not change what the document means.

    Two independent gates, because each is blind to what the other sees: the
    rendered form must match, and the block structure must be unchanged.
    """
    if not structurally_stable(before, after):
        return False
    left = canonical(before)
    right = canonical(after)
    return left is not None and right is not None and left == right


def findings(
    path: Path, classified: Classified, config: ProseConfig, rewrite: Rewrite
) -> list[Finding]:
    """Report one finding per prose block whose reflowed form differs."""
    severity = config.severity("reflow")
    by_number = {line.number: line for line in classified.lines}
    return [
        Finding(
            path=path,
            line=number,
            column=0,
            check="reflow",
            rule="reflow",
            message="prose block is not in semantic-line-break form",
            severity=severity,
            excerpt=make_excerpt(by_number[number].text, 0),
            fixable=True,
        )
        for number in rewrite.changed
    ]
