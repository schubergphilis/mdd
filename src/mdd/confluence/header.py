"""Strip export header and insert MDD footer in Confluence round-trip.

Also handles the body callout that links the published office attachment,
which uses the same strip-then-insert pattern as the MDD footer.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from mdd.mirror.registry import default_backend
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Export header strip
# ---------------------------------------------------------------------------

# Matches a blockquote block that starts with **Confluence export**
# The blockquote is a run of lines starting with "> " or ">"
# We match it at the very beginning of the body (after optional leading blank lines).
_EXPORT_HEADER_RE = re.compile(
    r"^([ \t]*\n)*"  # optional leading blank lines
    r"((?:>(?:[^\n]*)?\n)+)"  # one or more blockquote lines
    r"\n?",  # optional trailing blank line
    re.MULTILINE,
)


def strip_export_header(body_md: str) -> str:
    """Remove the leading Confluence export callout blockquote.

    The rule:
    - Find the first blockquote at the start of the body (after any blank lines).
    - If its first non-blank quoted line starts with ``**Confluence export**``,
      drop the entire blockquote and the immediately-following blank line.
    - If no such block is present, return unchanged.
    """
    m = _EXPORT_HEADER_RE.match(body_md)
    if m is None:
        return body_md

    block = m.group(2)  # the blockquote itself

    # Check first non-blank line of the blockquote
    first_line = ""
    for raw_line in block.splitlines():
        line = raw_line.lstrip()
        if line.startswith(">"):
            # Strip leading > and optional space
            content = line[1:].lstrip()
            if content:
                first_line = content
                break

    if not first_line.startswith("**Confluence export**"):
        return body_md

    # Drop the matched block (leading blanks + blockquote + trailing blank)
    return body_md[m.end() :]


# ---------------------------------------------------------------------------
# Export-title H1 strip
# ---------------------------------------------------------------------------


def _match_leading_h1(body_md: str) -> tuple[str, int] | None:
    """Return ``(title, end)`` for a leading ATX H1, or ``None``.

    ``end`` is the offset just past the H1 line, its preceding blank lines
    and one optional trailing blank line. Optional closing ``#`` characters
    and surrounding whitespace are not part of the title.
    """
    pos = 0
    while True:
        nl = body_md.find("\n", pos)
        if nl == -1:
            return None
        if body_md[pos:nl].strip(" \t"):
            break
        pos = nl + 1
    line = body_md[pos:nl]
    if not line.startswith("#") or line[1:2] not in (" ", "\t"):
        return None
    title = line[1:].strip(" \t").rstrip("#").rstrip(" \t")
    end = nl + 1
    next_nl = body_md.find("\n", end)
    if next_nl != -1 and not body_md[end:next_nl].strip(" \t"):
        end = next_nl + 1
    return title, end


def strip_export_title_h1(body_md: str, title: str) -> str:
    """Remove a leading ATX H1 whose text equals ``title``.

    The export side prepends ``# {title}`` so the markdown file is self-contained
    (the page title is metadata in Confluence, not part of the storage XHTML).
    On update we strip that leading H1 — re-emitting it would duplicate the title.

    If the first non-blank block is not an H1, or its text does not match
    ``title`` (after whitespace stripping), the body is returned unchanged.
    Empty ``title`` is treated as a no-op.
    """
    if not title:
        return body_md

    m = _match_leading_h1(body_md)
    if m is None:
        return body_md

    h1_title, end = m
    if h1_title.strip() != title.strip():
        return body_md

    return body_md[end:]


# ---------------------------------------------------------------------------
# MDD footer insert/replace
# ---------------------------------------------------------------------------

_FOOTER_PATTERN = re.compile(
    r"<p><sub><em>MDD markdown version of this page at .*?</em></sub></p>",
    re.DOTALL,
)


def _build_footer(mirror_url: str) -> str:
    escaped = mirror_url.replace("&", "&amp;").replace('"', "&quot;")
    return (
        f"<p><sub><em>MDD markdown version of this page at "
        f'<a href="{escaped}">{escaped}</a></em></sub></p>'
    )


def insert_mdd_footer(body_xhtml: str, mirror_url: str | None) -> str:
    """Insert or replace the MDD footer in storage XHTML.

    If ``mirror_url`` is ``None``, emit a warning to stderr and return ``body_xhtml``
    unchanged.

    The footer is idempotent: if a prior footer matching
    ``MDD markdown version of this page at`` is present, it is replaced; otherwise
    the footer is appended.
    """
    if mirror_url is None:
        log.warning("no mirror URL for this file; MDD footer will not be inserted.")
        return body_xhtml

    footer = _build_footer(mirror_url)

    if _FOOTER_PATTERN.search(body_xhtml):
        return _FOOTER_PATTERN.sub(footer, body_xhtml)

    return body_xhtml + "\n" + footer


# ---------------------------------------------------------------------------
# Mirror URL lookup
# ---------------------------------------------------------------------------


def get_mirror_url(md_path: Path) -> str | None:
    """Return the browse URL for *md_path* in its mirror, or ``None``.

    Which host is "ours" and what a browse URL looks like there is deployment
    knowledge, so this asks the registered default
    :class:`~mdd.mirror.protocol.MirrorBackend` rather than holding
    a host of its own. ``None`` — no backend wired (library use), the backend
    has no browse convention, or the file is not in a mirror it recognises —
    means the footer is left out.
    """
    try:
        backend = default_backend()
    except RuntimeError:
        # No dispatcher wired this process; nothing can claim a URL.
        return None
    return backend.web_url(md_path)


# ---------------------------------------------------------------------------
# Office-attachment callout
# ---------------------------------------------------------------------------

_CALLOUT_PREFIX = "<p><sub><em>Download as "
_CALLOUT_CLOSE = "</em></sub></p>"
_CALLOUT_SENTINEL = "(this attachment is generated from the markdown source)"


def _build_office_callout(links: list[tuple[str, str]]) -> str:
    """Build the office-attachment callout paragraph.

    Args:
        links: List of (url, filename) pairs — one per published format.

    Returns:
        A ``<p><sub><em>…</em></sub></p>`` string.
    """
    parts: list[str] = []
    for url, filename in links:
        safe_url = url.replace("&", "&amp;").replace('"', "&quot;")
        safe_name = filename.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(f'<a href="{safe_url}">{safe_name}</a>')
    downloads = ", ".join(parts)
    return f"<p><sub><em>Download as {downloads} {_CALLOUT_SENTINEL}</em></sub></p>"


def _find_office_callout(body_xhtml: str) -> tuple[int, int] | None:
    """Locate our callout paragraph as ``[start, end)``, or ``None``.

    The sentinel string identifies our own callout as opposed to any
    user-written paragraph. Plain ``str.find`` anchors keep this linear on
    bodies that repeat the prefix many times.
    """
    start = body_xhtml.find(_CALLOUT_PREFIX)
    if start == -1:
        return None
    sentinel = body_xhtml.find(_CALLOUT_SENTINEL, start + len(_CALLOUT_PREFIX))
    if sentinel == -1:
        return None
    close = body_xhtml.find(_CALLOUT_CLOSE, sentinel + len(_CALLOUT_SENTINEL))
    if close == -1:
        return None
    end = close + len(_CALLOUT_CLOSE)
    if body_xhtml.startswith("\n", end):
        end += 1
    return start, end


def strip_office_callout(body_xhtml: str) -> str:
    """Remove the office-attachment callout from storage XHTML.

    Idempotent: if no callout is present, returns *body_xhtml* unchanged.
    """
    while (span := _find_office_callout(body_xhtml)) is not None:
        start, end = span
        body_xhtml = body_xhtml[:start] + body_xhtml[end:]
    return body_xhtml


def insert_office_callout(body_xhtml: str, links: list[tuple[str, str]]) -> str:
    """Insert or replace the office-attachment callout in storage XHTML.

    The callout is placed at the very beginning of the body (before all other
    content).  If a prior callout is present (matched by the sentinel string),
    it is replaced; otherwise the callout is prepended.

    Args:
        body_xhtml: Current Confluence storage XHTML.
        links: List of (url, filename) pairs — one per published format.

    Returns:
        Updated storage XHTML.
    """
    callout = _build_office_callout(links)

    span = _find_office_callout(body_xhtml)
    if span is not None:
        start, end = span
        return body_xhtml[:start] + callout + strip_office_callout(body_xhtml[end:])

    return callout + "\n" + body_xhtml
