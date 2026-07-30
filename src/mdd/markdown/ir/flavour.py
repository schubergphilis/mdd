"""Configured markdown-it-py parser for the mdd markdown flavour.

The flavour:

    CommonMark core + table + strikethrough + linkify + tasklists
    + custom fenced_div (callouts + confluence-macro)
    + custom confluence_inline_macro
    (confluence_fence handled as a named fence in the reader)

Returns a fully-configured, reusable ``MarkdownIt`` instance.
"""

from __future__ import annotations

from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin

from .callouts import fenced_div_plugin
from .inline_macros import confluence_inline_macro_plugin

# Detect optional dep ``linkifyit-py`` at module load time. ``markdown-it-py``
# only enables its ``linkify`` rule when the package is importable; we mirror
# that probe here so ``build_md`` doesn't repeat it on every call.
try:
    import linkify_it as _li  # pyright: ignore[reportMissingImports, reportMissingTypeStubs]

    _linkify_available = _li is not None
except ImportError:
    _linkify_available = False


def build_md() -> MarkdownIt:
    """Return a ``MarkdownIt`` instance with the full mdd extension set."""
    _linkify = _linkify_available
    md = MarkdownIt("commonmark", {"html": True, "breaks": False, "linkify": _linkify})
    rules_to_enable = ["table", "strikethrough"]
    if _linkify:
        rules_to_enable.append("linkify")
    md.enable(rules_to_enable)
    md.use(tasklists_plugin)
    md.use(fenced_div_plugin)
    md.use(confluence_inline_macro_plugin)
    return md
