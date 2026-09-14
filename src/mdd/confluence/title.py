"""Derive the Confluence page title for a local Markdown file.

One rule, shared by ``create-page``, ``update-page`` and the relative-link
resolver, so a page and every link pointing at it agree on the title:

1. an explicit ``--title`` flag, when the caller has one;
2. a non-empty top-level ``title:`` string in the frontmatter — the key a
   plain documentation repository already carries, distinct from the
   ``confluence.title`` mirror field that ``export-page`` writes and that
   goes stale as soon as the page is renamed;
3. the first ATX H1 in the body;
4. the file stem.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_H1_RE = re.compile(r"^#\s+(.+)", re.MULTILINE)


def first_h1(body_md: str) -> str | None:
    """Return the text of the first ATX H1 heading in *body_md*, or ``None``."""
    m = _H1_RE.search(body_md)
    return m.group(1).strip() if m else None


def frontmatter_title(frontmatter: Mapping[str, object]) -> str | None:
    """Return the top-level ``title:`` when it is a non-empty string, else ``None``.

    Only a plain string counts. YAML happily parses ``title: 2026`` as an
    integer and ``title:`` as ``None``; neither is a title an author meant,
    so both fall through to the H1 rule rather than being stringified.
    """
    raw = frontmatter.get("title")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def resolve_page_title(
    frontmatter: Mapping[str, object],
    body_md: str,
    md_path: Path,
    *,
    cli_title: str | None = None,
) -> str:
    """Apply the title rule: flag, frontmatter ``title``, first H1, file stem."""
    if cli_title:
        return cli_title
    return frontmatter_title(frontmatter) or first_h1(body_md) or md_path.stem
