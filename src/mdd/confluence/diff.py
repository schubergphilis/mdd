"""Unified diff of Confluence storage XHTML."""

from __future__ import annotations

import difflib
import html.entities
import re

# Spans where whitespace, including where lines break, is load-bearing: code
# macros, preformatted blocks and CDATA sections. A code macro holds a CDATA
# body and no nested macros, so the first closing tag after it is its own.
# Self-closing tags (``/>``) have no body and are not matched, so the lazy
# match cannot run on to the closing tag of a later element.
_WHITESPACE_SIGNIFICANT_RE = re.compile(
    r'<ac:structured-macro\b[^>]*\bac:name=["\']code["\'][^>]*(?<!/)>.*?</ac:structured-macro>'
    r"|<pre\b[^>]*(?<!/)>.*?</pre>"
    r"|<!\[CDATA\[.*?\]\]>",
    re.IGNORECASE | re.DOTALL,
)

# A newline together with the spaces and blank lines around it.
_NEWLINE_RUN_RE = re.compile(r"[ \t\r]*\n[ \t\r\n]*")

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


def _whitespace_significant_spans(xhtml: str) -> list[str]:
    """Return every code macro, preformatted block and CDATA section in *xhtml*.

    Character references are decoded first, the same way :func:`_normalize`
    does, so an entity and its literal character compare equal.
    """
    return _WHITESPACE_SIGNIFICANT_RE.findall(_decode_safe_entities(xhtml))


def _join_soft_breaks(text: str) -> str:
    """Replace newlines inside a text run with a single space.

    A soft line break in Markdown renders as a literal newline in storage
    XHTML, and Confluence renders it as a space. A newline counts as part of
    a text run unless it sits between two tags (``>`` before, ``<`` after);
    those newlines separate blocks and keep the line structure of the diff.
    """

    def _replace(m: re.Match[str]) -> str:
        before = text[m.start() - 1] if m.start() > 0 else ""
        after = text[m.end()] if m.end() < len(text) else ""
        if not before or not after:
            return m.group(0)
        if before == ">" and after == "<":
            return m.group(0)
        return " "

    return _NEWLINE_RUN_RE.sub(_replace, text)


def _join_soft_breaks_outside_code(xhtml: str) -> str:
    """Apply :func:`_join_soft_breaks` everywhere except in whitespace-significant spans."""
    parts: list[str] = []
    pos = 0
    for m in _WHITESPACE_SIGNIFICANT_RE.finditer(xhtml):
        parts.append(_join_soft_breaks(xhtml[pos : m.start()]))
        parts.append(m.group(0))
        pos = m.end()
    parts.append(_join_soft_breaks(xhtml[pos:]))
    return "".join(parts)


def _normalize(xhtml: str) -> list[str]:
    """Normalize XHTML for diffing.

    - Join soft line breaks inside text runs, outside code blocks.
    - Collapse runs of whitespace (spaces, tabs) to a single space per line.
    - Strip leading and trailing whitespace from each line.
    - Decode typography character references to their literal characters.
    - Drop blank lines.
    """
    decoded = _join_soft_breaks_outside_code(_decode_safe_entities(xhtml))
    lines: list[str] = []
    for raw_line in decoded.splitlines():
        normalized = re.sub(r"[ \t]+", " ", raw_line).strip()
        if normalized:
            lines.append(normalized + "\n")
    return lines


def unified_xhtml_diff(local: str, remote: str) -> str:
    """Return a unified diff of two XHTML strings after normalization.

    Whitespace-only differences are normalized away for ordinary prose markup,
    including where a soft line break falls inside a text run.

    When the normalized diff is empty but the raw strings differ AND their
    code blocks (``<ac:structured-macro ac:name="code">``, ``<pre>`` or CDATA)
    differ, the function falls back to a raw line diff with a leading hint
    line. This prevents indentation and line-break changes inside code blocks
    from being silently swallowed.

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

    # Raw inputs differ.  If a code block differs, the whitespace difference
    # is inside it and therefore load-bearing.  Differences outside code
    # blocks (such as where a soft break falls) stay normalized away.
    if _whitespace_significant_spans(local) != _whitespace_significant_spans(remote):
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
                "# Note: whitespace-only differences detected inside a code block "
                "(indentation may be load-bearing)\n"
            )
            return hint + "".join(raw_diff)

    return ""
