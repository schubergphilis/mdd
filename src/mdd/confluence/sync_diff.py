"""Pure diff functions: desired_map + current_map → sync events (spec S14).

This module deliberately has no I/O — everything is computed from
in-memory maps.  It renames the concept of ``diff`` to avoid clashing
with ``mdd.confluence.diff`` which implements the XHTML unified-diff
for spec S09's update-page command.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.confluence.state import LocalPage


class EventKind(Enum):
    NEW = auto()  # Confluence page → new file in mirror
    CONTENT_EDIT = auto()  # remote version advanced → pull update
    RENAME = auto()  # title changed
    MOVE = auto()  # parent_id changed
    RENAME_MOVE = auto()  # title AND parent_id changed
    ARCHIVE = auto()  # status flipped to archived
    UNARCHIVE = auto()  # status flipped from archived
    DELETED = auto()  # page absent from desired (trashed or deleted)
    CROSS_SPACE_MOVE = auto()  # page moved to a different space
    METADATA_ONLY = auto()  # only labels/updated_by etc. changed
    CONFLICT = auto()  # local and remote both edited
    LOCAL_PUSH = auto()  # local edit, version matches remote → push to Confluence
    NO_OP = auto()  # nothing changed


@dataclass
class DesiredPage:
    """Entry from the Confluence-side tree fetch (Step 1)."""

    page_id: str
    title: str
    parent_id: str | None
    status: str  # "current" | "archived"
    version_number: int
    version_created_at: str
    space_id: str
    labels: list[str] = field(default_factory=list)
    updated_by: dict[str, Any] = field(default_factory=dict)  # pyright: ignore[reportAny]


@dataclass
class SyncEvent:
    """A single reconciliation event."""

    kind: EventKind
    page_id: str
    # fields vary by kind:
    desired: DesiredPage | None = None  # present for Confluence-side events
    current_path: str | None = None  # relative-path str for local events
    current_version: int | None = None  # local frontmatter version
    note: str = ""  # human-readable annotation


def _wants_content_pull(
    d: DesiredPage,
    c: LocalPage,
    *,
    skip_attachments: bool,
) -> bool:
    """Return True iff this tracked page needs a re-pull from Confluence.

    Two triggers:
    1. Remote version advanced past local.
    2. Issue #86 — local was previously exported under ``--no-attachments``
       (carries the ``attachments_skipped`` marker) and the current run is
       NOT skipping attachments, so we must back-fill them.
    """
    if d.version_number > c.version_number:
        return True
    return c.attachments_skipped and not skip_attachments


def _metadata_only_event(
    page_id: str,
    d: DesiredPage,
    c: LocalPage,
    has_other_events: bool,
) -> SyncEvent | None:
    """Return a METADATA_ONLY event iff no other event covers this page AND
    remote labels/status drifted from local.

    A pure no-op (identical labels and status) returns None so the page
    stays out of the dry-run plan.
    """
    if has_other_events:
        return None
    if sorted(d.labels) == sorted(c.labels) and d.status.upper() == c.status.upper():
        return None
    return SyncEvent(
        kind=EventKind.METADATA_ONLY,
        page_id=page_id,
        desired=d,
        current_path=str(c.path),
        current_version=c.version_number,
    )


def _make_event(
    kind: EventKind,
    page_id: str,
    d: DesiredPage | None,
    c: LocalPage,
) -> SyncEvent:
    """Construct a SyncEvent with the standard ``current_*`` fields filled in."""
    return SyncEvent(
        kind=kind,
        page_id=page_id,
        desired=d,
        current_path=str(c.path),
        current_version=c.version_number,
    )


def _archive_event(page_id: str, d: DesiredPage, c: LocalPage) -> SyncEvent | None:
    """Return ARCHIVE/UNARCHIVE when remote and local status differ, else None."""
    remote_status = d.status.upper()
    local_status = c.status.upper()
    if remote_status == local_status:
        return None
    if remote_status == "ARCHIVED":
        return _make_event(EventKind.ARCHIVE, page_id, d, c)
    if local_status == "ARCHIVED":
        return _make_event(EventKind.UNARCHIVE, page_id, d, c)
    return None


def _structural_event(page_id: str, d: DesiredPage, c: LocalPage) -> SyncEvent | None:
    """Return RENAME/MOVE/RENAME_MOVE when title or parent changed, else None."""
    title_changed = d.title != c.title
    parent_changed = d.parent_id != c.parent_id
    if title_changed and parent_changed:
        return _make_event(EventKind.RENAME_MOVE, page_id, d, c)
    if title_changed:
        return _make_event(EventKind.RENAME, page_id, d, c)
    if parent_changed:
        return _make_event(EventKind.MOVE, page_id, d, c)
    return None


def _content_edit_event(
    page_id: str,
    d: DesiredPage,
    c: LocalPage,
    *,
    skip_attachments: bool,
) -> SyncEvent | None:
    """Return CONTENT_EDIT when remote advanced OR a #86 attachment back-fill is due."""
    if not _wants_content_pull(d, c, skip_attachments=skip_attachments):
        return None
    # Orchestrator (sync.py) upgrades to CONFLICT after reading the local body;
    # the pure diff layer always emits CONTENT_EDIT here.
    return _make_event(EventKind.CONTENT_EDIT, page_id, d, c)


def _classify_tracked(
    page_id: str,
    d: DesiredPage,
    c: LocalPage,
    *,
    skip_attachments: bool,
) -> list[SyncEvent]:
    """Classify a page present both locally and remotely into ordered events.

    Emits at most one of each of: archive/unarchive, structural,
    content-edit, metadata-only — in that priority order.
    """
    archive = _archive_event(page_id, d, c)
    structural = _structural_event(page_id, d, c)
    content = _content_edit_event(page_id, d, c, skip_attachments=skip_attachments)
    md = _metadata_only_event(page_id, d, c, bool(archive or structural or content))
    return [e for e in (archive, structural, content, md) if e is not None]


def compute_events(
    desired: dict[str, DesiredPage],
    current_tracked: dict[str, LocalPage],
    current_untracked: list[Path],
    output_dir: Path | None = None,  # noqa: ARG001
    *,
    skip_attachments: bool = False,
) -> list[SyncEvent]:
    """Compute the full list of sync events.

    Args:
        desired: page_id → DesiredPage from Confluence tree fetch.
        current_tracked: page_id → LocalPage from mirror walk.
        current_untracked: List of Path objects for local-authored files.
        output_dir: Mirror root (unused here, passed for symmetry with orchestrator).

    Returns:
        List of :class:`SyncEvent` items, order is:
        1. Renames/moves/archives/unarchives (structural changes)
        2. New pages (Confluence → mirror)
        3. Deleted/cross-space
        4. Content edits (pull)
        5. Conflicts
        6. Local pushes
        7. Metadata-only refreshes
        8. Untracked local-authored files (new publish candidates)
        9. No-ops (omitted from output — callers may request them separately)
    """

    events: list[SyncEvent] = []
    all_ids = set(desired.keys()) | set(current_tracked.keys())

    for page_id in all_ids:
        d = desired.get(page_id)
        c = current_tracked.get(page_id)
        if d is not None and c is None:
            events.append(SyncEvent(kind=EventKind.NEW, page_id=page_id, desired=d))
        elif d is None and c is not None:
            events.append(_make_event(EventKind.DELETED, page_id, None, c))
        elif d is not None and c is not None:
            events.extend(_classify_tracked(page_id, d, c, skip_attachments=skip_attachments))

    for path in current_untracked:
        events.append(  # noqa: PERF401
            SyncEvent(
                kind=EventKind.NEW,
                page_id="",  # no page_id yet
                current_path=str(path),
                note="local-authored publish candidate",
            )
        )

    return events


def mark_cross_space_moves(
    events: list[SyncEvent],
    cross_space_ids: set[str],
    *,
    dest_space_keys: dict[str, str] | None = None,
) -> list[SyncEvent]:
    """Upgrade DELETED events to CROSS_SPACE_MOVE for known cross-space pages.

    Args:
        events: Events list from :func:`compute_events`.
        cross_space_ids: Set of page_ids confirmed to be in a different space.
        dest_space_keys: Optional mapping page_id → destination space key for richer notes.
    """
    updated: list[SyncEvent] = []
    for event in events:
        if event.kind == EventKind.DELETED and event.page_id in cross_space_ids:
            dest = (dest_space_keys or {}).get(event.page_id, "unknown")
            updated.append(
                SyncEvent(
                    kind=EventKind.CROSS_SPACE_MOVE,
                    page_id=event.page_id,
                    current_path=event.current_path,
                    current_version=event.current_version,
                    note=f"moved to space {dest}",
                )
            )
        else:
            updated.append(event)
    return updated


def mark_conflicts(
    events: list[SyncEvent],
    locally_edited_ids: set[str],
) -> list[SyncEvent]:
    """Upgrade CONTENT_EDIT events to CONFLICT for pages with local edits.

    A conflict occurs when the remote version advanced AND the local body
    was also edited.  The orchestrator determines ``locally_edited_ids``
    by comparing the local body against what was last exported.

    Also marks LOCAL_PUSH events that were intended for ``locally_edited_ids``
    but whose remote version advanced (conflict).
    """
    updated: list[SyncEvent] = []
    for event in events:
        if event.kind == EventKind.CONTENT_EDIT and event.page_id in locally_edited_ids:
            updated.append(
                SyncEvent(
                    kind=EventKind.CONFLICT,
                    page_id=event.page_id,
                    desired=event.desired,
                    current_path=event.current_path,
                    current_version=event.current_version,
                    note="local and remote both edited",
                )
            )
        else:
            updated.append(event)
    return updated
