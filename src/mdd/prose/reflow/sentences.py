"""Sentence segmentation for the reflow.

Rule-based, and deliberately conservative: a missed boundary leaves two
sentences on one line, while a false boundary splits ``e.g. this`` in half and
reads as damage in review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mdd.prose.config import ReflowConfig

_TERMINATORS = ".!?"
_ELLIPSIS_MIN = 3
_WORD_TAIL = re.compile(r"[\w.'’-]+$", re.UNICODE)


@dataclass(frozen=True)
class Segment:
    """A half-open ``[start, end)`` range within the joined block text."""

    start: int
    end: int


def _run_end(text: str, index: int) -> int:
    end = index
    while end < len(text) and text[end] in _TERMINATORS:
        end += 1
    return end


def _is_ellipsis(run: str) -> bool:
    return set(run) == {"."} and len(run) >= _ELLIPSIS_MIN


def _preceding_word(text: str, index: int) -> str:
    match = _WORD_TAIL.search(text[:index])
    return match.group(0) if match is not None else ""


def _is_abbreviation(text: str, index: int, config: ReflowConfig) -> bool:
    """True when the period at *index* closes a known abbreviation."""
    word = _preceding_word(text, index) + "."
    lowered = word.lower()
    return any(candidate in config.abbreviations for candidate in (word, lowered))


def _is_initial(text: str, index: int, config: ReflowConfig) -> bool:
    """True when the period at *index* follows a single-letter initial."""
    if index == 0:
        return False
    letter = text[index - 1]
    if not letter.isalpha() or not letter.isupper():
        return False
    if letter in config.single_letter_words:
        return False
    return index == 1 or not text[index - 2].isalnum()


def _followed_by_new_sentence(text: str, end: int) -> bool:
    """True when what follows *end* can start a sentence."""
    if end >= len(text):
        return True
    if text[end] not in " \t":
        return False
    rest = text[end:].lstrip()
    return not rest or not rest[0].islower()


def _is_boundary(text: str, index: int, end: int, config: ReflowConfig) -> bool:
    run = text[index:end]
    if _is_ellipsis(run):
        return False
    if not _followed_by_new_sentence(text, end):
        return False
    if run != ".":
        return True
    return not _is_abbreviation(text, index, config) and not _is_initial(text, index, config)


def segment(text: str, masked: Sequence[bool], config: ReflowConfig) -> list[Segment]:
    """Split *text* into sentence ranges, ignoring terminators inside masked spans."""
    out: list[Segment] = []
    start = 0
    index = 0
    while index < len(text):
        if text[index] not in _TERMINATORS or masked[index]:
            index += 1
            continue
        end = _run_end(text, index)
        if not _is_boundary(text, index, end, config):
            index = end
            continue
        out.append(Segment(start, end))
        while end < len(text) and text[end] in " \t":
            end += 1
        start = end
        index = end
    if start < len(text):
        out.append(Segment(start, len(text)))
    return out
