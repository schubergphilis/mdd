"""Bracket and quotation nesting, shared by the sentence and clause splitters.

Both splitters must agree on what "inside a quotation" means. If they did not,
the sentence splitter could put a line break where the clause splitter had
decided it was inside a parenthesis, and the other way round.

Delimiters are the bracket pairs ``()``, ``[]`` and ``{}``, the curly double
quotes and the guillemets, which nest, and the straight double quote, which
toggles because its opening and closing forms are the same character. Single
quotes are not delimiters: ``it's`` and ``the tools’ output`` use the same
characters as a single-quoted phrase, and treating them as quotes would
suppress every break after the first apostrophe.

The scan runs in both directions and a position is nested when either direction
says so. For balanced text the two agree. For unbalanced text the union is
deliberately conservative: an unmatched opener nests everything after it, and
an unmatched closer, or an odd straight quote, nests everything before it. A
missed break leaves two sentences on one line; a break in the wrong place splits
a quotation in half.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

_OPENERS = "([{“«"
_CLOSERS = ")]}”»"
_STRAIGHT_QUOTE = '"'


def _nested_positions(
    text: str, masked: Sequence[bool], order: Iterable[int], openers: str, closers: str
) -> Iterator[int]:
    """Scan *order* once, yielding every position that sits inside a pair."""
    depth = 0
    in_quote = False
    for index in order:
        if masked[index]:
            continue
        char = text[index]
        if char in openers:
            depth += 1
        elif char in closers:
            depth = max(0, depth - 1)
        elif char == _STRAIGHT_QUOTE:
            in_quote = not in_quote
        elif depth or in_quote:
            yield index


def nested_flags(text: str, masked: Sequence[bool], start: int, end: int) -> list[bool]:
    """Return, for each position in ``text[start:end]``, whether it sits inside a pair.

    Masked positions and the delimiters themselves are never flagged; neither
    caller considers them as a break point.
    """
    nested = [False] * (end - start)
    forward = _nested_positions(text, masked, range(start, end), _OPENERS, _CLOSERS)
    backward = _nested_positions(text, masked, range(end - 1, start - 1, -1), _CLOSERS, _OPENERS)
    for index in (*forward, *backward):
        nested[index - start] = True
    return nested
