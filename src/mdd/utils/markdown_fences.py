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

_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _closes(line: str, fence: str) -> bool:
    """Return True if *line* is a closing fence for the opener *fence*."""
    if len(line) - len(line.lstrip(" ")) > 3:
        return False
    stripped = line.strip()
    return len(stripped) >= len(fence) and stripped == fence[0] * len(stripped)


def find_fenced_code_blocks(text: str) -> list[tuple[int, int]]:
    """Return ``[start, end)`` character spans of fenced code blocks in *text*.

    Each span covers the opening fence line through the closing fence line,
    excluding the newline that ends the closing line. An unterminated fence
    runs to the end of the text.
    """
    spans: list[tuple[int, int]] = []
    fence: str | None = None
    start = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if fence is None:
            m = _FENCE_OPEN_RE.match(body)
            if m:
                fence = m.group(1)
                start = offset
        elif _closes(body, fence):
            spans.append((start, offset + len(body)))
            fence = None
        offset += len(line)
    if fence is not None:
        spans.append((start, len(text)))
    return spans


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
