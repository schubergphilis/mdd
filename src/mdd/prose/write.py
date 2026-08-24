"""The shared write path for both writers.

The mirror refusal, the atomic replace and the per-file ``info`` log live here
once and both ``reflow --write`` and ``lint --write`` call them. Two copies of
this logic is how one of them quietly loses the mirror check.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from mdd.prose.report import Finding
from mdd.prose.rules import CROSS_CUTTING
from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.prose.config import ProseConfig

log = get_logger(__name__)


def mirror_reason(text: str) -> str | None:
    """Return why *text* is a mirrored file, or ``None`` when it is authored content.

    A file is mirrored if its frontmatter carries ``confluence.page_id`` or a
    ``sharepoint.sync`` block. Rewriting one invalidates SharePoint's content
    hash and bumps Confluence's mtime, both of which fail silently and neither
    of which looks like a prose problem when it surfaces.
    """
    split = split_frontmatter(text)
    if split is None:
        return None
    mapping = parse_yaml_mapping(split[0])
    if mapping is None:
        return None
    confluence = mapping.get("confluence")
    if isinstance(confluence, dict) and "page_id" in confluence:
        return "confluence.page_id"
    sharepoint = mapping.get("sharepoint")
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
            f"{reason} marks this file as a mirror; rewriting it invalidates the "
            f"sync's change detection. Pass --allow-mirror to {check} anyway."
        ),
        severity=config.severity("mirrored-file"),
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
