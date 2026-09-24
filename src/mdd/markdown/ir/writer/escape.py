"""Escape helpers for the IR → markdown writer."""

from __future__ import annotations

import re


def render_attr_dict(params: dict[str, str]) -> str:
    parts: list[str] = []
    for key, value in params.items():
        parts.append(f'{key}="{escape_attr(value)}"')
    return " ".join(parts)


def escape_attr(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


_CM_ESCAPABLE_PUNCT = r"""!"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~"""

# Characters in a ``Text`` node that the reader would otherwise take as
# inline structure. Each alternative matches exactly one character; the
# replacement prefixes it with a backslash (CommonMark §2.4 backslash
# escapes cover every ASCII punctuation character).
_INLINE_ESCAPE_RE = re.compile(
    # A backslash before ASCII punctuation is itself an escape sequence, so
    # a literal one must be doubled for the reader to yield it back.
    rf"\\(?=[{_CM_ESCAPABLE_PUNCT}])"
    # ``<`` opens raw HTML, an autolink, a comment or a processing
    # instruction only when followed by one of these.
    r"|<(?=[A-Za-z/!?])"
    # Link/image brackets, code spans and ``*`` emphasis in any position.
    r"|[\[\]`*]"
    # ``_`` emphasis cannot open or close between two alphanumerics.
    r"|(?<![^\W_])_|_(?![^\W_])"
    # ``{{`` starts a confluence inline-macro marker.
    r"|\{(?=\{)"
    # ``~~`` opens strikethrough; ``~~~`` opens a fence.
    r"|~(?=~)|(?<=~)~"
    # ``&name;`` / ``&#NN;`` / ``&#xHH;`` are decoded as entities.
    r"|&(?=(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9a-fA-F]+);)"
)

# Line-leading shapes that would start a block (or end the paragraph) when
# the line is read back. Group 1 is the leading indentation; the backslash
# goes right after it.
_BLOCK_START_RE = re.compile(
    r"^( {0,3})(?:"
    r"#{1,6}(?:\s|$)"  # ATX heading
    r"|[-+](?:\s|$)"  # bullet list item
    r"|[>|]"  # blockquote; table row
    r"|-+\s*$"  # setext underline / thematic break
    r"|=+\s*$"  # setext underline
    r"|:{3,}"  # fenced div
    r")"
)
# ``1.`` / ``1)`` ordered-list markers: the digit cannot be escaped (only
# punctuation can), so the backslash goes before the ``.`` or ``)``.
_ORDERED_START_RE = re.compile(r"^( {0,3}\d{1,9})[.)](?:\s|$)")
# GFM table delimiter row (``| --- | :-: |``). Escaping its first ``-``
# stops the previous line from being read as a header row.
_TABLE_DELIMITER_RE = re.compile(r"^(\s*\|?\s*:?)-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")

# CommonMark autolinks (`<scheme:rest>`) require an absolute URI with a
# scheme followed by ``:``; whitespace and ``<`` / ``>`` in the URI itself
# would break the form (the reader would close the autolink early).
_AUTOLINK_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>]+$")


def is_safe_autolink(href: str) -> bool:
    return _AUTOLINK_RE.match(href) is not None


def _escape_block_start(line: str) -> str:
    for pattern in (_ORDERED_START_RE, _TABLE_DELIMITER_RE, _BLOCK_START_RE):
        m = pattern.match(line)
        if m:
            cut = m.end(1)
            return f"{line[:cut]}\\{line[cut:]}"
    return line


def escape_text(text: str, *, line_start: bool = False) -> str:
    """Escape *text* so the reader yields it back as literal text.

    With ``line_start`` the first character of *text* begins a line of a
    paragraph; every character after a newline inside *text* always does.
    Line-leading block markers are escaped only in that position.
    """
    escaped = _INLINE_ESCAPE_RE.sub(r"\\\g<0>", text)
    if "\n" not in escaped and not line_start:
        return escaped
    lines = escaped.split("\n")
    for i, line in enumerate(lines):
        if i > 0 or line_start:
            lines[i] = _escape_block_start(line)
    return "\n".join(lines)


def escape_url(url: str) -> str:
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
