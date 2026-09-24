"""Locate fenced code blocks in markdown with a single line scan.

A regex with a backreference to the opening fence backtracks across every
candidate opener when the document contains many fences, which is
superlinear on large inputs. Walking the lines once with an "inside a
fence" flag is linear and matches CommonMark closing rules: a closing
fence uses the same character, is at least as long as the opener, and
carries nothing but whitespace.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _closes(line: str, fence: str) -> bool:
    """Return True if *line* is a closing fence for the opener *fence*."""
    if len(line) - len(line.lstrip(" ")) > 3:
        return False
    stripped = line.strip()
    return len(stripped) >= len(fence) and stripped == fence[0] * len(stripped)


def iter_fenced_code_blocks(text: str, pos: int = 0) -> Iterator[tuple[int, int]]:
    """Yield ``[start, end)`` character spans of fenced code blocks in order.

    Each span covers the opening fence line through the closing fence line,
    excluding the newline that ends the closing line. An unterminated fence
    runs to the end of the text.

    Scanning starts at the first line boundary at or after *pos*: a fence
    opener has to begin its line, so a partial line at *pos* cannot open one.
    Lines before *pos* are not looked at, so a fence opened before *pos* does
    not carry over. Consumers that only need the next block stop the generator
    early and pay for the lines walked, not for the whole text.
    """
    if pos > 0 and text[pos - 1] != "\n":
        nl = text.find("\n", pos)
        if nl == -1:
            return
        pos = nl + 1
    fence: str | None = None
    start = 0
    while pos < len(text):
        nl = text.find("\n", pos)
        end = len(text) if nl == -1 else nl + 1
        body = text[pos:end].rstrip("\r\n")
        if fence is None:
            m = _FENCE_OPEN_RE.match(body)
            if m:
                fence = m.group(1)
                start = pos
        elif _closes(body, fence):
            yield (start, pos + len(body))
            fence = None
        pos = end
    if fence is not None:
        yield (start, len(text))


def find_fenced_code_blocks(text: str) -> list[tuple[int, int]]:
    """Return every span ``iter_fenced_code_blocks`` yields for *text*."""
    return list(iter_fenced_code_blocks(text))


def blank_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace every non-newline character inside *spans* with a space.

    Newlines are kept so line and column offsets outside the spans stay put.
    *spans* must be sorted and non-overlapping.
    """
    out: list[str] = []
    pos = 0
    for start, end in spans:
        out.append(text[pos:start])
        out.append("".join("\n" if ch == "\n" else " " for ch in text[start:end]))
        pos = end
    out.append(text[pos:])
    return "".join(out)


def remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Return *text* with every span cut out. *spans* must be sorted and non-overlapping."""
    out: list[str] = []
    pos = 0
    for start, end in spans:
        out.append(text[pos:start])
        pos = end
    out.append(text[pos:])
    return "".join(out)
