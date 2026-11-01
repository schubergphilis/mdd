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

Only a matched pair nests. A delimiter without a partner is ignored, because
in technical prose it is far more often an enumeration (``a)``), an inch mark
(``5"``) or a smiley than a quotation that runs past the end of the paragraph,
and treating it as one would put the rest of the paragraph on a single line.
A straight double quote opens a pair when it follows whitespace, an opening
bracket or the start of the text and precedes a non-space, and closes one when
it follows a non-space and precedes whitespace, punctuation or the end.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_OPENERS = "([{\u201c\u00ab"
_CLOSERS = ")]}\u201d\u00bb"
_STRAIGHT_QUOTE = '"'
_DELIMITERS = _OPENERS + _CLOSERS + _STRAIGHT_QUOTE
_CLOSING_PUNCTUATION = ".,;:!?)]}\u201d\u00bb"


def _straight_quote_role(text: str, index: int, start: int, end: int) -> str:
    """Say whether the straight quote at *index* opens, closes, or neither."""
    before = text[index - 1] if index > start else " "
    after = text[index + 1] if index + 1 < end else " "
    opens = (before.isspace() or before in _OPENERS) and not after.isspace()
    closes = not before.isspace() and (after.isspace() or after in _CLOSING_PUNCTUATION)
    if opens and not closes:
        return "open"
    if closes and not opens:
        return "close"
    return ""


def _matched_pairs(
    text: str, masked: Sequence[bool], start: int, end: int
) -> list[tuple[int, int]]:
    """Return the (opener, closer) positions of every matched pair in ``text[start:end]``."""
    pairs: list[tuple[int, int]] = []
    stack: list[tuple[str, int]] = []
    for index in range(start, end):
        if masked[index]:
            continue
        char = text[index]
        if char == _STRAIGHT_QUOTE:
            role = _straight_quote_role(text, index, start, end)
            if role == "open":
                stack.append((char, index))
                continue
            if role == "":
                continue
            want = _STRAIGHT_QUOTE
        elif char in _OPENERS:
            stack.append((char, index))
            continue
        elif char in _CLOSERS:
            want = _OPENERS[_CLOSERS.index(char)]
        else:
            continue
        for depth in range(len(stack) - 1, -1, -1):
            if stack[depth][0] == want:
                pairs.append((stack[depth][1], index))
                del stack[depth:]
                break
    return pairs


def nested_flags(text: str, masked: Sequence[bool], start: int, end: int) -> list[bool]:
    """Return, for each position in ``text[start:end]``, whether it sits inside a pair.

    Masked positions and the delimiters themselves are never flagged; neither
    caller considers them as a break point.
    """
    nested = [False] * (end - start)
    for opener, closer in _matched_pairs(text, masked, start, end):
        for index in range(opener + 1, closer):
            if not masked[index] and text[index] not in _DELIMITERS:
                nested[index - start] = True
    return nested
