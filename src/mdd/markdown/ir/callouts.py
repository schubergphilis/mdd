"""Custom markdown-it-py plugin: fenced div → Callout / ConfluenceMacro.

Parses ``:::callout-<kind>`` … ``:::`` blocks (and ``:::confluence-macro``).
Written in-house (~50 LOC) to avoid an external plugin dep with a different
fence syntax shape than the mdd markdown flavour uses.

Wire-up: ``md.use(fenced_div_plugin)`` in flavour.py.

Token emitted per block::

    container_{name}_open   (info = trailing text after the name)
    ... inner tokens ...
    container_{name}_close

This matches the interface of ``mdit_py_plugins.container`` so the reader
can use the same ``container_*_open`` pattern for both.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from markdown_it import MarkdownIt
    from markdown_it.rules_block import StateBlock

_FENCE_OPEN = re.compile(r"^(:{3,})\s*(\S+)(.*)")
_KNOWN_NAMES = (
    "callout-tip",
    "callout-info",
    "callout-note",
    "callout-warning",
    "callout-panel",
    "confluence-macro",
    "layout",
    "layout-section",
    "layout-cell",
)


def fenced_div_plugin(md: MarkdownIt) -> None:
    """Register block rule that parses ``:::name ...`` fenced divs."""
    md.block.ruler.before(
        "fence",
        "fenced_div",
        _fenced_div_rule,
        {"alt": ["paragraph", "reference", "blockquote", "list"]},
    )


def _fenced_div_rule(
    state: StateBlock,
    startLine: int,
    endLine: int,
    silent: bool,
) -> bool:
    pos = state.bMarks[startLine] + state.tShift[startLine]
    maximum = state.eMarks[startLine]
    line_text = state.src[pos:maximum]

    m = _FENCE_OPEN.match(line_text)
    if not m:
        return False

    fence_char_count = len(m.group(1))
    name = m.group(2)
    info = m.group(3).strip()

    if name not in _KNOWN_NAMES:
        return False

    if silent:
        return True

    open_line = startLine
    nextLine = startLine + 1
    found = False

    while nextLine < endLine:
        p = state.bMarks[nextLine] + state.tShift[nextLine]
        mx = state.eMarks[nextLine]
        ln = state.src[p:mx].rstrip()
        if ln == ":" * fence_char_count:
            found = True
            break
        nextLine += 1

    open_token = state.push(f"container_{name}_open", "div", 1)
    open_token.markup = ":" * fence_char_count
    open_token.block = True
    open_token.info = info
    open_token.map = [open_line, nextLine]

    state.md.block.tokenize(state, open_line + 1, nextLine)

    close_token = state.push(f"container_{name}_close", "div", -1)
    close_token.markup = ":" * fence_char_count
    close_token.block = True

    state.line = nextLine + (1 if found else 0)
    return True
