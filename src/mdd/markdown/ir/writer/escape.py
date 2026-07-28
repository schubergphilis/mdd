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
_BACKSLASH_BEFORE_PUNCT_RE = re.compile(rf"\\(?=[{_CM_ESCAPABLE_PUNCT}])")

# CommonMark autolinks (`<scheme:rest>`) require an absolute URI with a
# scheme followed by ``:``; whitespace and ``<`` / ``>`` in the URI itself
# would break the form (the reader would close the autolink early).
_AUTOLINK_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>]+$")


def is_safe_autolink(href: str) -> bool:
    return _AUTOLINK_RE.match(href) is not None


def escape_text(text: str) -> str:
    # CommonMark §6.1: the parser strips a backslash before any ASCII
    # punctuation character. To preserve a literal backslash before such a
    # character (e.g. `\.` should round-trip as `\.`, not `.`), double the
    # backslash so the reader's escape pass yields a single literal back.
    return _BACKSLASH_BEFORE_PUNCT_RE.sub(r"\\\\", text)


def escape_url(url: str) -> str:
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
