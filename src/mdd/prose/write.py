"""The shared write path for both writers.

The mirror refusal, the write-gate refusal, the atomic replace and the
per-file ``info`` log live here once and both ``reflow --write`` and
``lint --write`` call them. Two copies of
this logic is how one of them quietly loses the mirror check.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from mdd.prose import frontmatter
from mdd.prose.report import Finding
from mdd.prose.rules import CROSS_CUTTING
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.prose.config import ProseConfig
    from mdd.prose.gate import Verdict

log = get_logger(__name__)

#: The mirror reason for front matter that is there but cannot be read.
UNREADABLE_FRONTMATTER = "front matter that cannot be parsed"


def mirror_reason(text: str) -> str | None:
    """Return why *text* may be a mirrored file, or ``None`` when it is authored content.

    A file is mirrored if its front matter carries ``confluence.page_id`` or a
    ``sharepoint.sync`` block. Rewriting one invalidates SharePoint's content
    hash and bumps Confluence's mtime, both of which fail silently and neither
    of which looks like a prose problem when it surfaces.

    Front matter that is there but cannot be read could hide either key, so it
    is treated as a mirror too: the guard fails closed.
    """
    front = frontmatter.read(text)
    if not front.present:
        return None
    if front.mapping is None:
        return UNREADABLE_FRONTMATTER
    confluence = front.mapping.get("confluence")
    if isinstance(confluence, dict) and "page_id" in confluence:
        return "confluence.page_id"
    sharepoint = front.mapping.get("sharepoint")
    if isinstance(sharepoint, dict) and "sync" in sharepoint:
        return "sharepoint.sync"
    return None


def mirror_finding(path: Path, check: str, reason: str, config: ProseConfig) -> Finding:
    """The finding a refused write reports."""
    return Finding(
        path=path,
        line=0,
        column=0,
        check=CROSS_CUTTING,
        rule="mirrored-file",
        message=(
            f"this file may be a mirror (found {reason}); rewriting a mirror invalidates "
            f"the sync's change detection. Pass --allow-mirror to {check} anyway."
        ),
        severity=config.severity("mirrored-file"),
    )


def refusal_finding(path: Path, check: str, verdict: Verdict, config: ProseConfig) -> Finding:
    """The finding a fix that failed the write gate reports, with or without ``--write``."""
    where = f"at line {verdict.line}: " if verdict.line > 0 else ""
    return Finding(
        path=path,
        line=verdict.line,
        column=0,
        check=CROSS_CUTTING,
        rule="not-equivalent",
        message=(
            f"the {check} fix would change the document ({where}{verdict.reason}); "
            f"--write leaves this file unchanged"
        ),
        severity=config.severity("not-equivalent"),
    )


def write_failure(path: Path, check: str, reason: str, config: ProseConfig) -> Finding:
    """The finding a refused or failed write reports."""
    return Finding(
        path=path,
        line=0,
        column=0,
        check=check,
        rule="write-failed",
        message=f"could not write the file: {reason}",
        severity=config.severity("write-failed"),
    )


def atomic_write(path: Path, text: str) -> None:
    """Write *text* to *path* via a temp file, ``fsync`` and rename.

    Line endings are written through unchanged: the caller has already decided
    what they should be.
    """
    if path.is_symlink():
        # os.replace would clobber the link with a regular file, silently
        # detaching it from its target. Refusing is the reversible choice.
        msg = f"refusing to rewrite {path}: it is a symlink"
        raise OSError(msg)
    tmp_path = path.with_suffix(path.suffix + ".mdd-prose.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="") as fh:
            _ = fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)  # noqa: PTH105
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    log.info("wrote %s", path)
