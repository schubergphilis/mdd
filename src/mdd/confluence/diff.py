"""Unified diff of Confluence storage XHTML."""

from __future__ import annotations

import difflib
import html.entities
import re

# Pattern matching the opening tag of a Confluence code structured-macro.
# Used to detect CDATA/code blocks where indentation is load-bearing.
_CODE_MACRO_RE = re.compile(
    r'<ac:structured-macro[^>]*\bac:name=["\']code["\']',
    re.IGNORECASE,
)

# Named entities kept literal so the diff still surfaces real bugs:
#   &amp; — bare `&` is malformed XHTML; we want that visible
#   &lt;/&gt; — bare `<`/`>` would change structure
_PRESERVED_ENTITIES: frozenset[str] = frozenset({"amp", "lt", "gt"})

_NAMED_ENTITY_RE = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_NUMERIC_ENTITY_RE = re.compile(r"&#(\d+);")
_HEX_ENTITY_RE = re.compile(r"&#x([0-9a-fA-F]+);")


def _decode_safe_entities(text: str) -> str:
    """Decode named/numeric character references to their literal characters.

    Typography entities (``&times;``, ``&rarr;``, ``&hellip;``, ``&mdash;`` …)
    round-trip through the IR pipeline as literal Unicode characters. To keep
    the diff focused on real changes, treat the two forms as equivalent here.
    ``&amp;``/``&lt;``/``&gt;`` are preserved verbatim so real encoding bugs
    still surface.
    """

    def _named(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in _PRESERVED_ENTITIES:
            return m.group(0)
        char = html.entities.html5.get(name + ";")
        return char if char is not None else m.group(0)

    def _numeric(m: re.Match[str]) -> str:
        try:
            return chr(int(m.group(1)))
        except ValueError, OverflowError:
            return m.group(0)

    def _hex(m: re.Match[str]) -> str:
        try:
            return chr(int(m.group(1), 16))
        except ValueError, OverflowError:
            return m.group(0)

    text = _HEX_ENTITY_RE.sub(_hex, text)
    text = _NUMERIC_ENTITY_RE.sub(_numeric, text)
    return _NAMED_ENTITY_RE.sub(_named, text)


def _contains_code_macro(xhtml: str) -> bool:
    """Return True if the XHTML contains a Confluence code macro."""
    return bool(_CODE_MACRO_RE.search(xhtml))


def _normalize(xhtml: str) -> list[str]:
    """Normalize XHTML for diffing.

    - Collapse runs of whitespace (spaces, tabs) to a single space per line.
    - Strip leading and trailing whitespace from each line.
    - Decode typography character references to their literal characters.
    - Drop blank lines.
    """
    decoded = _decode_safe_entities(xhtml)
    lines: list[str] = []
    for raw_line in decoded.splitlines():
        normalized = re.sub(r"[ \t]+", " ", raw_line).strip()
        if normalized:
            lines.append(normalized + "\n")
    return lines


def unified_xhtml_diff(local: str, remote: str) -> str:
    """Return a unified diff of two XHTML strings after normalization.

    Whitespace-only differences are normalized away for ordinary prose markup.

    When the normalized diff is empty but the raw strings differ AND at least
    one of them contains a ``<ac:structured-macro ac:name="code">`` block, the
    function falls back to a raw character-level diff with a leading hint line.
    This prevents indentation changes inside code/CDATA blocks from being
    silently swallowed.

    Returns an empty string if there are no meaningful differences.
    """
    local_lines = _normalize(local)
    remote_lines = _normalize(remote)

    diff = list(
        difflib.unified_diff(
            remote_lines,
            local_lines,
            fromfile="remote",
            tofile="local",
        )
    )
    normalized_diff = "".join(diff)

    if normalized_diff:
        return normalized_diff

    # Normalized diff is empty — check whether raw inputs actually differ
    if local == remote:
        return ""

    # Raw inputs differ.  If either side contains a code macro, the whitespace
    # difference may be inside a CDATA block and therefore load-bearing.
    if _contains_code_macro(local) or _contains_code_macro(remote):
        raw_diff = list(
            difflib.unified_diff(
                remote.splitlines(keepends=True),
                local.splitlines(keepends=True),
                fromfile="remote",
                tofile="local",
            )
        )
        if raw_diff:
            hint = (
                "# Note: whitespace-only differences detected inside a code macro "
                "(indentation may be load-bearing)\n"
            )
            return hint + "".join(raw_diff)

    return ""
