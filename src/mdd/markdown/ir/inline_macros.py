"""Custom markdown-it-py plugins for Confluence inline shapes.

Two rules:

1. ``confluence_inline_macro_plugin`` — recognises
   ``{{confluence:name key="value"}}`` and ``{{confluence-raw:BASE64}}``
   markers as single inline tokens (type ``confluence_inline``).

2. ``confluence_fence_plugin`` — recognises ` ```confluence-xml` fenced
   code blocks and emits a ``confluence_fence`` block token so the reader
   can distinguish them from ordinary code fences.

Both are wired into the parser in ``flavour.py``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from markdown_it import MarkdownIt
    from markdown_it.rules_inline import StateInline

_MACRO_RE = re.compile(r"\{\{confluence:([A-Za-z0-9_-]+)((?:\s+[^=}]+=\"[^\"]*\")*)\s*\}\}")
_RAW_RE = re.compile(r"\{\{confluence-raw:([A-Za-z0-9+/=]+)\}\}")


def confluence_inline_macro_plugin(md: MarkdownIt) -> None:
    """Register inline rule for ``{{confluence:...}}`` and ``{{confluence-raw:...}}``."""
    md.inline.ruler.push("confluence_inline", _confluence_inline_rule)


def _confluence_inline_rule(state: StateInline, silent: bool) -> bool:
    src = state.src
    pos = state.pos

    if pos >= len(src) or src[pos] != "{":
        return False
    if pos + 1 >= len(src) or src[pos + 1] != "{":
        return False

    # Try macro first, then raw fallback.
    for pattern in (_MACRO_RE, _RAW_RE):
        m = pattern.match(src, pos)
        if m:
            if not silent:
                token = state.push("confluence_inline", "", 0)
                token.content = m.group(0)
                token.markup = m.group(0)
            state.pos = m.end()
            return True

    return False
