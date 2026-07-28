"""Strip export header and insert MDD footer in Confluence round-trip (spec S09 + 017).

Spec S17 adds a body callout that links the published office attachment.
The callout uses the same strip-then-insert pattern as the MDD footer.
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

# Matches the leading ATX H1 line (allows trailing whitespace, optional closing #s),
# plus any blank lines before and one blank line after.
_TITLE_H1_RE = re.compile(
    r"^([ \t]*\n)*"  # optional leading blank lines
    r"#[ \t]+(?P<title>[^\n]*?)[ \t]*#*[ \t]*\n"  # the H1 line itself
    r"([ \t]*\n)?",  # optional trailing blank line
)


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

    m = _TITLE_H1_RE.match(body_md)
    if m is None:
        return body_md

    if m.group("title").strip() != title.strip():
        return body_md

    return body_md[m.end() :]


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
    :class:`~mdd.mirror.protocol.MirrorBackend` (spec S44) rather than holding
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
# Office-attachment callout (spec S17)
# ---------------------------------------------------------------------------

# Matches the callout paragraph inserted by spec S17, plus an optional following newline.
# The sentinel string "(this attachment is generated from the markdown source)"
# is how we identify our own callout vs any user-written paragraph.
_OFFICE_CALLOUT_PATTERN = re.compile(
    r"<p><sub><em>Download as .*?\(this attachment is generated from the markdown source\)"
    r".*?</em></sub></p>\n?",
    re.DOTALL,
)

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


def strip_office_callout(body_xhtml: str) -> str:
    """Remove the office-attachment callout from storage XHTML.

    Idempotent: if no callout is present, returns *body_xhtml* unchanged.
    """
    return _OFFICE_CALLOUT_PATTERN.sub("", body_xhtml)


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

    if _OFFICE_CALLOUT_PATTERN.search(body_xhtml):
        return _OFFICE_CALLOUT_PATTERN.sub(callout, body_xhtml)

    return callout + "\n" + body_xhtml
