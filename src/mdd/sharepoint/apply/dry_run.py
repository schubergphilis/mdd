"""Dry-run plan printer for SharePoint sync."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from mdd.sharepoint.diff import SyncState, classify_pair, read_sync_state

if TYPE_CHECKING:
    from pathlib import Path


def print_dry_run_plan(
    pairs: list[tuple[Path | None, Path | None]],
    *,
    output_dir: Path,  # noqa: ARG001
) -> None:
    """Print the dry-run plan to stdout without touching any files.

    Program output for piping — intentionally uses ``print`` so it goes to
    stdout. ``# noqa: T201`` will be required here once the orchestrator
    enables ``T201`` in :file:`pyproject.toml` (issue #122).
    """
    print("[dry-run] Sync plan:")  # noqa: T201
    for docx_path, md_path in pairs:
        # Re-read sync state from md if it exists
        sync_state = (
            read_sync_state(md_path)
            if md_path is not None
            else SyncState(
                office_sha256_at_sync=None,
                md_sha256_at_sync=None,
                last_sync=None,
                converter_version=None,
                update_office=False,
            )
        )
        action = classify_pair(docx_path, md_path, sync_state=sync_state)
        office_name = docx_path.name if docx_path is not None else "<none>"
        md_name = md_path.name if md_path is not None else "<none>"
        print(f"  {office_name} / {md_name} → {action}")  # noqa: T201
    sys.stdout.flush()
