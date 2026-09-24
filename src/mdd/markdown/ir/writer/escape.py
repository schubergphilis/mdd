"""Escape helpers for the IR → markdown writer."""

from __future__ import annotations

import base64
import re
import urllib.parse

from mdd.utils.logging import get_logger

from .._patterns import FENCE_ATTR_B64_PREFIX, KEY_RE

log = get_logger(__name__)


def render_attr_dict(params: dict[str, str]) -> str:
    parts: list[str] = []
    for key, value in params.items():
        parts.append(f'{key}="{escape_attr(value)}"')
    return " ".join(parts)


# Characters a fenced-div header value cannot carry verbatim: the header is
# a single line read up to the first ``}``, markdown-it rewrites CR and NUL,
# and Python's ``str.splitlines`` treats the other C0 separators and the
# Unicode line/paragraph separators as line breaks. Tab is harmless.
_FENCE_UNSAFE_RE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f\x85\u2028\u2029}]")


def _fence_value_needs_encoding(value: str) -> bool:
    return value.startswith(FENCE_ATTR_B64_PREFIX) or _FENCE_UNSAFE_RE.search(value) is not None


def render_fence_attr_dict(params: dict[str, str]) -> str:
    """Render *params* for a ``:::name {…}`` fenced-div header line.

    Values the header cannot hold verbatim are written as
    ``confluence-b64:<base64 of the UTF-8 value>``; the reader decodes them.
    A parameter whose name the reader cannot parse back (anything outside
    letters, digits, ``_`` and ``-``) is left out with a warning, so the
    name can never split or extend the header line.
    """
    parts: list[str] = []
    for key, value in params.items():
        if not is_attr_key(key):
            log.warning("dropping macro parameter with unsupported name %r", key)
            continue
        if _fence_value_needs_encoding(value):
            encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
            parts.append(f'{key}="{FENCE_ATTR_B64_PREFIX}{encoded}"')
        else:
            parts.append(f'{key}="{escape_attr(value)}"')
    return " ".join(parts)


def is_attr_key(key: str) -> bool:
    """Return whether *key* is a parameter name the markdown reader parses back."""
    return KEY_RE.fullmatch(key) is not None


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


# Characters that end or alter an unbracketed link destination when read
# back: whitespace (Unicode whitespace too, which is trimmed at the end of a
# destination) and control characters end it, parentheses must balance, a
# leading ``<`` switches to the bracketed form, a backslash starts an escape
# and ``&name;`` is decoded as an entity. ``>`` goes with ``<``. Each is
# percent-encoded as UTF-8; the reader percent-decodes the destination.
_URL_ESCAPE_RE = re.compile(
    r"[\s\x00-\x1f\x7f-\x9f()<>\\]|&(?=(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9a-fA-F]+);)"
)


def escape_url(url: str) -> str:
    return _URL_ESCAPE_RE.sub(lambda m: urllib.parse.quote(m.group(0), safe=""), url)
