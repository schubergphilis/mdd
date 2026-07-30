"""Path/type filters and blacklist gating for mdd search.

Provides:
- ``filter_blacklisted`` — drop MirrorRoot entries that are on the blacklist.
- ``frontmatter_line_range`` — detect the YAML frontmatter block in a file so
  matches inside it can be excluded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mdd.utils.blacklist import (
    BlacklistConfigError,
    BlacklistError,
    check_confluence,
    check_sharepoint,
)
from mdd.utils.logging import get_logger

log = get_logger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.search.roots import MirrorRoot


def filter_blacklisted(
    roots: list[MirrorRoot],
    *,
    blacklist_file: Path | None = None,
) -> list[MirrorRoot]:
    """Return a new list with blacklisted roots removed.

    Silently skips roots whose source type is neither 'confluence' nor
    'sharepoint' (docs, extra dirs, and any source a wrapper registered) —
    the blacklist only governs Confluence spaces and SharePoint sites.

    If the blacklist config file is missing or malformed a warning is printed
    to stderr and the root is *kept* — fail-open, because local-only reads are
    unrestricted.
    """
    filtered: list[MirrorRoot] = []
    for root in roots:
        if root.source_type == "confluence":
            try:
                check_confluence(root.identifier, blacklist_file=blacklist_file)
                filtered.append(root)
            except BlacklistError:
                pass  # drop silently
            except BlacklistConfigError as exc:
                log.warning(
                    "blacklist config error while checking %s: %s",
                    root.mirror_name,
                    exc,
                )
                filtered.append(root)  # fail-open
        elif root.source_type == "sharepoint":
            try:
                check_sharepoint(root.identifier, blacklist_file=blacklist_file)
                filtered.append(root)
            except BlacklistError:
                pass  # drop silently
            except BlacklistConfigError as exc:
                log.warning(
                    "blacklist config error while checking %s: %s",
                    root.mirror_name,
                    exc,
                )
                filtered.append(root)  # fail-open
        else:
            # docs, extra, wrapper-registered sources — not governed by the blacklist
            filtered.append(root)
    return filtered


def frontmatter_line_range(path: Path) -> tuple[int, int] | None:
    """Return the inclusive 1-based line range of the YAML frontmatter block.

    Returns ``(start, end)`` where *start* is 1 (the ``---`` opener) and
    *end* is the line number of the closing ``---``.  Returns ``None`` if the
    file does not start with a frontmatter block.

    Only reads the first 200 lines to avoid loading large files into memory.
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            # Read just enough lines
            lines: list[str] = []
            for _ in range(200):
                raw = fh.readline()
                if not raw:
                    break
                lines.append(raw)
    except OSError:
        return None

    if not lines or lines[0].rstrip("\r\n") != "---":
        return None

    for i, line in enumerate(lines[1:], start=2):
        if line.rstrip("\r\n") == "---":
            return (1, i)

    return None


def is_frontmatter_line(line_number: int, fm_range: tuple[int, int] | None) -> bool:
    """Return True if *line_number* (1-based) falls within the frontmatter block."""
    if fm_range is None:
        return False
    return fm_range[0] <= line_number <= fm_range[1]
