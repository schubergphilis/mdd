"""Git mv / rm helpers and attachment dir management for sync."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mdd.confluence.paths import sanitize
from mdd.confluence.sync_diff import EventKind, SyncEvent
from mdd.mirror.errors import MirrorError
from mdd.mirror.orchestrator import git_commit as _mirror_git_commit

# ``is_dirty`` is re-exported from :mod:`mdd.utils.git` so existing
# ``from mdd.confluence.apply import is_dirty`` continues to work (issue #123).
from mdd.utils.git import (
    GitError,
    run_git,
)
from mdd.utils.git import (
    is_dirty as is_dirty,
)
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path

log = get_logger(__name__)


class ApplyError(Exception):
    """Raised when a git operation fails during apply."""


def _git(args: list[str], cwd: Path, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a git command in *cwd*, raising :class:`ApplyError` on failure.

    Thin wrapper around :func:`mdd.utils.git.run_git` that re-raises
    :class:`GitError` as :class:`ApplyError` to preserve this module's
    boundary exception.
    """
    try:
        return run_git(args, cwd, timeout=timeout)
    except GitError as exc:
        raise ApplyError(str(exc)) from exc


def git_mv(src: Path, dst: Path, repo_dir: Path) -> None:
    """Move *src* to *dst* using ``git mv``.

    Creates parent directories as needed (git doesn't do that for us).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    _git(["mv", str(src), str(dst)], repo_dir)


def git_rm(path: Path, repo_dir: Path, *, recursive: bool = False) -> None:
    """Remove *path* using ``git rm``.

    If *recursive* is True, uses ``git rm -r``.
    """
    args = ["rm", "-r", "--", str(path)] if recursive else ["rm", "--", str(path)]
    _git(args, repo_dir)


def git_add(path: Path, repo_dir: Path) -> None:
    """Stage *path* (or a directory) with ``git add``."""
    _git(["add", "--", str(path)], repo_dir)


def git_commit(repo_dir: Path, message: str) -> bool:
    """Commit all staged changes.

    Thin shim over :func:`mdd.mirror.orchestrator.git_commit` that
    preserves the historic ``bool`` return shape and re-raises
    :class:`~mdd.mirror.errors.MirrorError` as :class:`ApplyError` so the
    :mod:`mdd.confluence.mutate` boundary keeps catching the same
    exception identity.
    """
    try:
        committed, _sha = _mirror_git_commit(repo_dir, message)
    except MirrorError as exc:
        raise ApplyError(str(exc)) from exc
    return committed


def attachments_dir(md_path: Path) -> Path:
    """Return the attachments directory sibling of *md_path*.

    Follows the convention ``<stem>-attachments/`` beside the ``.md``.
    """
    return md_path.parent / f"{md_path.stem}-attachments"


def move_attachments_alongside(
    old_md: Path,
    new_md: Path,
    repo_dir: Path,
) -> None:
    """Move the attachments directory alongside the new .md path.

    If no attachments directory exists for *old_md*, does nothing.
    """
    old_att = attachments_dir(old_md)
    if not old_att.exists():
        return

    new_att = attachments_dir(new_md)
    if old_att == new_att:
        return

    git_mv(old_att, new_att, repo_dir)


def compute_rename_path(
    current_path: Path,
    new_title: str,
    new_parent_dir: Path,
    page_id: str,
    used_paths: set[Path],
) -> Path:
    """Compute the new filesystem path for a renamed/moved page.

    Args:
        current_path: Existing ``.md`` path.
        new_title: Sanitized title for the new filename.
        new_parent_dir: Target directory.
        page_id: Confluence page ID (used for disambiguation).
        used_paths: Set of paths already allocated in this sync run.

    Returns:
        The new path (may include ``(page_id)`` suffix to disambiguate).
    """
    safe_name = sanitize(new_title) if new_title else f"page-{page_id}"
    candidate = new_parent_dir / f"{safe_name}.md"

    if candidate != current_path and (candidate.exists() or candidate in used_paths):
        # Collision: we need to add page_id suffix to both files
        candidate = new_parent_dir / f"{safe_name} ({page_id}).md"

    used_paths.add(candidate)
    return candidate


def resolve_collision_pair(
    path_a: Path,
    page_id_a: str,
    path_b: Path,
    page_id_b: str,
    repo_dir: Path,
) -> tuple[Path, Path]:
    """Rename both *path_a* and *path_b* to include their page IDs.

    Result: ``Title (12345).md`` and ``Title (67890).md``.
    Both get the suffix — not just the newcomer.

    Returns the new paths (a, b).
    """
    stem = path_a.stem
    parent = path_a.parent
    ext = path_a.suffix

    new_a = parent / f"{stem} ({page_id_a}){ext}"
    new_b = parent / f"{stem} ({page_id_b}){ext}"

    # Only rename if needed
    if path_a != new_a:
        git_mv(path_a, new_a, repo_dir)
    if path_b != new_b:
        git_mv(path_b, new_b, repo_dir)

    return new_a, new_b


_PLAN_KIND_LABELS: list[tuple[Any, str]] = []  # populated lazily to avoid import cycles


def _plan_kind_labels() -> list[tuple[Any, str]]:
    if not _PLAN_KIND_LABELS:
        _PLAN_KIND_LABELS.extend(
            [
                (EventKind.RENAME, "Renames"),
                (EventKind.MOVE, "Moves"),
                (EventKind.RENAME_MOVE, "Rename+Move"),
                (EventKind.ARCHIVE, "Archives"),
                (EventKind.UNARCHIVE, "Unarchives"),
                (EventKind.NEW, "New pages (Confluence → mirror)"),
                (EventKind.DELETED, "Deleted/trashed"),
                (EventKind.CROSS_SPACE_MOVE, "Cross-space moves"),
                (EventKind.CONTENT_EDIT, "Content updates (pull)"),
                (EventKind.CONFLICT, "Conflicts"),
                (EventKind.LOCAL_PUSH, "Local pushes"),
                (EventKind.METADATA_ONLY, "Metadata refreshes"),
            ]
        )
    return _PLAN_KIND_LABELS


def _print_plan_section(label: str, items: list[SyncEvent]) -> None:
    log.info("%s: %d", label, len(items))
    for ev in items[:5]:  # show at most 5 per category
        path_str = ev.current_path or ""
        desired = ev.desired
        title = desired.title if desired else ""
        detail = title or path_str or ev.page_id
        note = f" [{ev.note}]" if ev.note else ""
        log.info("    - %s%s", detail, note)
    if len(items) > 5:
        log.info("    ... and %d more", len(items) - 5)


def print_plan_summary(
    events: list[SyncEvent],
    *,
    head: int | None = None,
) -> None:
    """Print a human-readable plan summary (for --dry-run mode)."""
    by_kind: dict[EventKind, list[SyncEvent]] = {}
    for event in events:
        by_kind.setdefault(event.kind, []).append(event)

    if not by_kind:
        return

    log.info("Sync plan (--dry-run):")

    for kind, label in _plan_kind_labels():
        items = by_kind.get(kind, [])
        if items:
            _print_plan_section(label, items)

    if head is not None:
        log.info("(--head %d: only first %d Confluence pages eligible)", head, head)
