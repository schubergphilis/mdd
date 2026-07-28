"""Detect local edits since the last export (sync step 3)."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mdd.confluence.frontmatter import read as read_frontmatter

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.confluence.state import LocalPage
    from mdd.confluence.sync_diff import DesiredPage


def detect_local_edits(
    tracked: dict[str, LocalPage],
    desired: dict[str, DesiredPage],
    output_dir: Path,  # noqa: ARG001
) -> set[str]:
    """Detect pages where the local body was edited since last export.

    A local edit is present when:
    - The page exists in both maps
    - The local version_number matches the remote version_number
    - The local file body differs from what was last exported

    For efficiency we don't re-render to storage XHTML here — we simply
    check if the local file's mtime is newer than the exported_at timestamp.
    The orchestrator will do a full diff before pushing.
    """
    locally_edited: set[str] = set()

    for page_id, local in tracked.items():
        remote = desired.get(page_id)
        if remote is None:
            continue

        # Only check when versions match (otherwise it's a pull scenario)
        if local.version_number != remote.version_number:
            continue

        # Read exported_at from frontmatter
        fm, _body = read_frontmatter(local.path)
        conf_raw: Any = fm.get("confluence")  # pyright: ignore[reportAny]
        if not isinstance(conf_raw, dict):
            continue
        conf: dict[str, Any] = conf_raw  # pyright: ignore[reportUnknownVariableType]
        exported_at_raw: Any = conf.get("exported_at")  # pyright: ignore[reportAny]
        if not isinstance(exported_at_raw, str) or not exported_at_raw:
            continue

        with suppress(ValueError, OSError):
            exported_dt = datetime.fromisoformat(exported_at_raw)
            mtime = datetime.fromtimestamp(local.path.stat().st_mtime, tz=UTC)
            if mtime > exported_dt:
                locally_edited.add(page_id)

    return locally_edited
