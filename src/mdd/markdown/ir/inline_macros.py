"""Custom markdown-it-py plugins for Confluence inline shapes.

Two rules:

1. ``confluence_inline_macro_plugin`` — recognises
   ``{{confluence:name key="value"}}`` and ``{{confluence-raw:BASE64}}``
   markers as single inline tokens (type ``confluence_inline``).

2. ``confluence_fence_plugin`` — recognises ` ```confluence-xml` fenced
   code blocks and emits a ``confluence_fence`` block token so the reader
   can distinguish them from ordinary code fences.

Both are wired into the parser in ``flavour.py``.

The marker regexes are shared with the reader — see
:mod:`mdd.markdown.ir._patterns`. Tokenising and parsing must agree on the
exact grammar, so there is one definition, not one per module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._patterns import INLINE_MACRO_RE, INLINE_RAW_RE

if TYPE_CHECKING:
    from markdown_it import MarkdownIt
    from markdown_it.rules_inline import StateInline


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
    for pattern in (INLINE_MACRO_RE, INLINE_RAW_RE):
        m = pattern.match(src, pos)
        if m:
            if not silent:
                token = state.push("confluence_inline", "", 0)
                token.content = m.group(0)
                token.markup = m.group(0)
            state.pos = m.end()
            return True

    return False
