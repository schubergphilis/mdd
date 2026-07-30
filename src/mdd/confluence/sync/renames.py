"""Rename / move / archive / unarchive event application.

The bulk handlers in this module — :func:`apply_renames_moves` and
:func:`apply_archive_unarchive` — are exposed as the single per-page entry
points used by the mutate orchestrators (:mod:`mdd.confluence.mutate`).
Single-event callers pass a one-element ``[event]`` list rather than
calling extracted per-event helpers, on the grounds that fewer touched
signatures means fewer ways to regress sync.

Callers that need to drive a single ``SyncEvent`` (rename, move,
archive, or unarchive) should simply build the event in the desired
``EventKind`` and call ``apply_renames_moves([event], ...)`` or
``apply_archive_unarchive([event], ...)``.  No API surface change is
required for the per-page case.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from mdd.confluence.apply import (
    ApplyError,
    compute_rename_path,
    git_mv,
    move_attachments_alongside,
)
from mdd.confluence.frontmatter import read as read_frontmatter
from mdd.confluence.frontmatter import write as write_frontmatter
from mdd.confluence.state import LocalPage
from mdd.confluence.sync_diff import EventKind, SyncEvent
from mdd.utils.logging import get_logger

from ._helpers import pin_mtime_to_exported_at

if TYPE_CHECKING:
    from ._types import SyncSummary

log = get_logger(__name__)


def _rename_kind_label(kind: EventKind) -> str:
    return {
        EventKind.RENAME: "rename",
        EventKind.MOVE: "move",
        EventKind.RENAME_MOVE: "rename+move",
    }[kind]


def _rewrite_first_h1(md_path: Path, new_title: str) -> None:
    """Rewrite the first ATX H1 (``# ...``) in *md_path*'s body to *new_title*.

    No-op when the body has no leading H1. The title-on-disk convention
    is "first body H1 wins" (see
    :func:`mdd.confluence.update._extract_title`), so a rename that does
    not also rewrite the H1 would leave the old title in place — and the
    next ``mdd confluence update-page`` would push the old title back to
    Confluence.
    """
    fm, body = read_frontmatter(md_path)
    lines = body.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        if line.startswith("# "):
            trailing = "\n" if line.endswith("\n") else ""
            lines[idx] = f"# {new_title}{trailing}"
            new_body = "".join(lines)
            write_frontmatter(md_path, fm, new_body)
            return


def _replace_tracked_path(mirror: Any, page_id: str, new_path: Path) -> None:  # pyright: ignore[reportAny]
    existing = mirror.tracked[page_id]  # pyright: ignore[reportAny]
    mirror.tracked[page_id] = LocalPage(  # pyright: ignore[reportAny]
        path=new_path,
        page_id=page_id,
        title=existing.title,  # pyright: ignore[reportAny]
        parent_id=existing.parent_id,  # pyright: ignore[reportAny]
        status=existing.status,  # pyright: ignore[reportAny]
        version_number=existing.version_number,  # pyright: ignore[reportAny]
        space_key=existing.space_key,  # pyright: ignore[reportAny]
        space_id=existing.space_id,  # pyright: ignore[reportAny]
        attachments_manifest=existing.attachments_manifest,  # pyright: ignore[reportAny]
    )


def _apply_one_rename_move(
    event: SyncEvent,
    mirror: Any,  # pyright: ignore[reportAny]
    output_dir: Path,
    page_to_outdir: dict[str, Path],
    used_paths: set[Path],
    summary: SyncSummary,
) -> None:
    if event.desired is None or event.current_path is None:
        return
    page_id = event.page_id
    current_path = Path(event.current_path)
    desired_page = event.desired
    kind_label = _rename_kind_label(event.kind)
    try:
        new_dir = page_to_outdir.get(page_id, current_path.parent)
        new_path = compute_rename_path(
            current_path, desired_page.title, new_dir, page_id, used_paths
        )
        if new_path != current_path:
            git_mv(current_path, new_path, output_dir)
            move_attachments_alongside(current_path, new_path, output_dir)
            log.info("%s: %s -> %s", kind_label, current_path.name, new_path.name)
        if event.kind in (EventKind.RENAME, EventKind.RENAME_MOVE):
            # Title-on-disk is the body H1;
            # rewriting it here keeps update-page from resurrecting the
            # old title via _extract_title.
            _rewrite_first_h1(new_path, desired_page.title)
        if page_id in mirror.tracked:  # pyright: ignore[reportAny]
            _replace_tracked_path(mirror, page_id, new_path)
        if event.kind in (EventKind.RENAME, EventKind.RENAME_MOVE):
            summary.renamed += 1
        if event.kind in (EventKind.MOVE, EventKind.RENAME_MOVE):
            summary.moved += 1
    except (ApplyError, OSError) as exc:
        log.error("%s %s: %s", kind_label, page_id, exc)
        summary.failures.append(f"{kind_label} {page_id}: {exc}")


def apply_renames_moves(
    events: list[SyncEvent],
    mirror: Any,  # pyright: ignore[reportAny]
    output_dir: Path,
    page_to_outdir: dict[str, Path],
    used_paths: set[Path],
    summary: SyncSummary,
) -> None:
    for event in events:
        if event.kind in (EventKind.RENAME, EventKind.MOVE, EventKind.RENAME_MOVE):
            _apply_one_rename_move(event, mirror, output_dir, page_to_outdir, used_paths, summary)


def resolve_path_after_rename(
    mirror: Any,  # pyright: ignore[reportAny]
    page_id: str,
    fallback: str | Path,
) -> Path:
    if page_id in mirror.tracked:  # pyright: ignore[reportAny]
        return mirror.tracked[page_id].path  # pyright: ignore[reportAny]
    return Path(fallback)


def _apply_one_archive(
    event: SyncEvent,
    mirror: Any,  # pyright: ignore[reportAny]
    summary: SyncSummary,
) -> None:
    if event.desired is None or event.current_path is None:
        return
    page_id = event.page_id
    current_path = resolve_path_after_rename(mirror, page_id, event.current_path)
    try:
        fm, body = read_frontmatter(current_path)
        conf_raw: Any = fm.get("confluence")  # pyright: ignore[reportAny]
        if not isinstance(conf_raw, dict):
            return
        conf: dict[str, Any] = conf_raw  # pyright: ignore[reportUnknownVariableType]
        if event.kind == EventKind.ARCHIVE:
            conf["status"] = "archived"
            summary.archived += 1
            log.info("archive: %s", current_path.name)
        else:
            conf["status"] = "current"
            summary.unarchived += 1
            log.info("unarchive: %s", current_path.name)
        write_frontmatter(current_path, fm, body)
        pin_mtime_to_exported_at(current_path, fm)
    except (OSError, Exception) as exc:
        label = "archive" if event.kind == EventKind.ARCHIVE else "unarchive"
        log.error("%s %s: %s", label, page_id, exc)
        summary.failures.append(f"{label} {page_id}: {exc}")


def apply_archive_unarchive(
    events: list[SyncEvent],
    mirror: Any,
    summary: SyncSummary,  # pyright: ignore[reportAny]
) -> None:
    for event in events:
        if event.kind in (EventKind.ARCHIVE, EventKind.UNARCHIVE):
            _apply_one_archive(event, mirror, summary)
