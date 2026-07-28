"""Deletion / cross-space-move application."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from mdd.confluence.apply import ApplyError, attachments_dir, git_rm
from mdd.confluence.sync_diff import EventKind, SyncEvent
from mdd.utils.logging import get_logger

from .finalize import is_git_repo

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._types import SyncOptions, SyncSummary

log = get_logger(__name__)


def _delete_path_git(path: Path, output_dir: Path) -> None:
    """Remove *path* (and its attachments dir, if present) via ``git rm``."""
    git_rm(path, output_dir)
    att_dir = attachments_dir(path)
    if att_dir.exists():
        git_rm(att_dir, output_dir, recursive=True)


def _delete_path_fs(path: Path) -> None:
    """Remove *path* (and its attachments dir, if present) via the filesystem.

    Used when the sync output directory is not a git working tree
    (e.g. ``--read-only`` mirrors or fresh ``--output`` directories): shelling
    out to ``git rm`` would fail with ``fatal: not a git repository`` (#88).
    """
    path.unlink(missing_ok=True)
    att_dir = attachments_dir(path)
    if att_dir.exists():
        shutil.rmtree(att_dir, ignore_errors=False)


def _delete_path(path: Path, output_dir: Path, summary: SyncSummary, label: str) -> bool:
    """Remove *path* (and its attachment dir, if present). Returns True on success.

    Branches on whether *output_dir* is a git working tree: git repos go through
    ``git rm`` so the index is updated alongside the worktree; plain mirrors use
    ``Path.unlink`` / ``shutil.rmtree`` (#88).
    """
    try:
        if is_git_repo(output_dir):
            _delete_path_git(path, output_dir)
        else:
            _delete_path_fs(path)
    except (ApplyError, OSError) as exc:
        log.error("%s: %s", label, exc)
        summary.failures.append(f"{label}: {exc}")
        return False
    return True


def _apply_delete_event(
    event: SyncEvent, output_dir: Path, opts: SyncOptions, summary: SyncSummary
) -> None:
    """Apply a DELETED event: remove the local page unless --no-delete is set."""
    if opts.no_delete:
        log.info("skip-delete: %s (--no-delete)", event.current_path)
        return
    if event.current_path is None:
        return
    current_path = Path(event.current_path)
    if _delete_path(current_path, output_dir, summary, f"delete {event.page_id}"):
        summary.deleted += 1
        log.info("delete: %s", current_path.name)


def _apply_cross_space_event(
    event: SyncEvent, output_dir: Path, opts: SyncOptions, summary: SyncSummary
) -> None:
    """Apply a CROSS_SPACE_MOVE event: record the move and delete locally (unless --no-delete)."""
    if event.current_path is None:
        return
    current_path = Path(event.current_path)
    summary.cross_space.append(f'"{current_path.name}" ({event.page_id}) — {event.note}')
    log.warning("cross-space %s: %s", current_path.name, event.note)
    if not opts.no_delete:
        _delete_path(current_path, output_dir, summary, f"delete (cross-space) {event.page_id}")


_DELETION_HANDLERS: dict[EventKind, Callable[[SyncEvent, Path, SyncOptions, SyncSummary], None]] = {
    EventKind.DELETED: _apply_delete_event,
    EventKind.CROSS_SPACE_MOVE: _apply_cross_space_event,
}


def apply_deletions(
    events: list[SyncEvent], output_dir: Path, opts: SyncOptions, summary: SyncSummary
) -> None:
    for event in events:
        handler = _DELETION_HANDLERS.get(event.kind)
        if handler is not None:
            handler(event, output_dir, opts, summary)
