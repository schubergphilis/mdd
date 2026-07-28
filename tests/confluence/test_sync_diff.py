"""Tests for confluence sync_diff pure functions (spec S14)."""

from __future__ import annotations

from pathlib import Path

from mdd.confluence.state import LocalPage
from mdd.confluence.sync_diff import (
    DesiredPage,
    EventKind,
    SyncEvent,
    compute_events,
    mark_conflicts,
    mark_cross_space_moves,
)


def make_desired(  # noqa: PLR0913
    page_id: str = "100",
    title: str = "Test Page",
    parent_id: str | None = None,
    status: str = "CURRENT",
    version_number: int = 5,
    space_id: str = "98306",
    labels: list[str] | None = None,
) -> DesiredPage:
    return DesiredPage(
        page_id=page_id,
        title=title,
        parent_id=parent_id,
        status=status,
        version_number=version_number,
        version_created_at="2026-01-01T00:00:00Z",
        space_id=space_id,
        labels=labels or [],
    )


def make_local(  # noqa: PLR0913
    page_id: str = "100",
    title: str = "Test Page",
    parent_id: str | None = None,
    status: str = "CURRENT",
    version_number: int = 5,
    path: str | Path = "test.md",
    labels: list[str] | None = None,
    attachments_skipped: bool = False,
) -> LocalPage:
    return LocalPage(
        path=Path(path),
        page_id=page_id,
        title=title,
        parent_id=parent_id,
        status=status,
        version_number=version_number,
        space_key="TEST",
        space_id="98306",
        labels=labels or [],
        attachments_skipped=attachments_skipped,
    )


class TestComputeEventsNoOp:
    def test_no_changes_produces_no_events(self) -> None:
        desired = {"100": make_desired()}
        current = {"100": make_local()}
        events = compute_events(desired, current, [])
        assert events == []

    def test_label_drift_produces_metadata_only(self) -> None:
        desired = {"100": make_desired(labels=["new-label"])}
        current = {"100": make_local()}
        events = compute_events(desired, current, [])
        assert len(events) == 1
        assert events[0].kind == EventKind.METADATA_ONLY

    def test_label_reorder_alone_is_noop(self) -> None:
        desired = {"100": make_desired(labels=["a", "b"])}
        current = {"100": make_local(labels=["b", "a"])}
        events = compute_events(desired, current, [])
        assert events == []

    def test_non_archive_status_drift_produces_metadata_only(self) -> None:
        desired = {"100": make_desired(status="DRAFT")}
        current = {"100": make_local(status="CURRENT")}
        events = compute_events(desired, current, [])
        assert len(events) == 1
        assert events[0].kind == EventKind.METADATA_ONLY


class TestComputeEventsNew:
    def test_page_only_in_desired_is_new(self) -> None:
        desired = {"100": make_desired()}
        current: dict[str, LocalPage] = {}
        events = compute_events(desired, current, [])
        assert len(events) == 1
        assert events[0].kind == EventKind.NEW
        assert events[0].page_id == "100"
        assert events[0].desired is not None

    def test_untracked_local_file_is_new_publish_candidate(self) -> None:
        desired: dict[str, DesiredPage] = {}
        current: dict[str, LocalPage] = {}
        untracked = [Path("new-page.md")]
        events = compute_events(desired, current, untracked)
        assert len(events) == 1
        assert events[0].kind == EventKind.NEW
        assert events[0].page_id == ""
        assert events[0].current_path == "new-page.md"
        assert "local-authored" in events[0].note


class TestComputeEventsDeleted:
    def test_page_only_in_current_is_deleted(self) -> None:
        desired: dict[str, DesiredPage] = {}
        current = {"100": make_local()}
        events = compute_events(desired, current, [])
        assert len(events) == 1
        assert events[0].kind == EventKind.DELETED
        assert events[0].page_id == "100"

    def test_deleted_event_has_current_path(self) -> None:
        desired: dict[str, DesiredPage] = {}
        current = {"100": make_local(path="docs/test.md")}
        events = compute_events(desired, current, [])
        assert events[0].current_path == "docs/test.md"


class TestComputeEventsContentEdit:
    def test_remote_version_advanced_is_content_edit(self) -> None:
        desired = {"100": make_desired(version_number=10)}
        current = {"100": make_local(version_number=5)}
        events = compute_events(desired, current, [])
        assert any(e.kind == EventKind.CONTENT_EDIT for e in events)

    def test_same_version_is_not_content_edit(self) -> None:
        desired = {"100": make_desired(version_number=5)}
        current = {"100": make_local(version_number=5)}
        events = compute_events(desired, current, [])
        assert not any(e.kind == EventKind.CONTENT_EDIT for e in events)


class TestComputeEventsAttachmentsBackfill:
    """Regression test for issue #86.

    After a sync run with ``--no-attachments``, exported pages carry an
    ``attachments_skipped: true`` marker.  On a subsequent run *without*
    that flag, ``compute_events`` must emit a ``CONTENT_EDIT`` for those
    pages even when the remote version has not advanced, so attachments
    get back-filled.  When the flag is still set on the new run, no
    event is emitted (the user is intentionally still text-only).
    """

    def test_skipped_marker_with_attachments_enabled_emits_content_edit(self) -> None:
        desired = {"100": make_desired(version_number=5)}
        current = {"100": make_local(version_number=5, attachments_skipped=True)}
        events = compute_events(desired, current, [], skip_attachments=False)
        assert any(e.kind == EventKind.CONTENT_EDIT and e.page_id == "100" for e in events), (
            "expected a CONTENT_EDIT to back-fill skipped attachments"
        )

    def test_skipped_marker_with_attachments_still_skipped_emits_nothing(self) -> None:
        desired = {"100": make_desired(version_number=5)}
        current = {"100": make_local(version_number=5, attachments_skipped=True)}
        events = compute_events(desired, current, [], skip_attachments=True)
        assert events == []

    def test_no_marker_no_version_advance_no_event(self) -> None:
        # Sanity: without the marker, nothing should fire.
        desired = {"100": make_desired(version_number=5)}
        current = {"100": make_local(version_number=5, attachments_skipped=False)}
        events = compute_events(desired, current, [], skip_attachments=False)
        assert events == []


class TestComputeEventsRename:
    def test_title_change_is_rename(self) -> None:
        desired = {"100": make_desired(title="New Title")}
        current = {"100": make_local(title="Old Title")}
        events = compute_events(desired, current, [])
        rename_events = [e for e in events if e.kind == EventKind.RENAME]
        assert len(rename_events) == 1
        assert rename_events[0].page_id == "100"

    def test_parent_change_is_move(self) -> None:
        desired = {"100": make_desired(parent_id="200")}
        current = {"100": make_local(parent_id="300")}
        events = compute_events(desired, current, [])
        move_events = [e for e in events if e.kind == EventKind.MOVE]
        assert len(move_events) == 1

    def test_both_title_and_parent_change_is_rename_move(self) -> None:
        desired = {"100": make_desired(title="New Title", parent_id="200")}
        current = {"100": make_local(title="Old Title", parent_id="300")}
        events = compute_events(desired, current, [])
        rm_events = [e for e in events if e.kind == EventKind.RENAME_MOVE]
        assert len(rm_events) == 1


class TestComputeEventsArchive:
    def test_status_to_archived_is_archive_event(self) -> None:
        desired = {"100": make_desired(status="ARCHIVED")}
        current = {"100": make_local(status="CURRENT")}
        events = compute_events(desired, current, [])
        archive_events = [e for e in events if e.kind == EventKind.ARCHIVE]
        assert len(archive_events) == 1

    def test_status_from_archived_is_unarchive_event(self) -> None:
        desired = {"100": make_desired(status="CURRENT")}
        current = {"100": make_local(status="ARCHIVED")}
        events = compute_events(desired, current, [])
        unarchive_events = [e for e in events if e.kind == EventKind.UNARCHIVE]
        assert len(unarchive_events) == 1

    def test_archive_status_lowercase_normalized(self) -> None:
        desired = {"100": make_desired(status="archived")}
        current = {"100": make_local(status="current")}
        events = compute_events(desired, current, [])
        archive_events = [e for e in events if e.kind == EventKind.ARCHIVE]
        assert len(archive_events) == 1


class TestMarkCrossSpaceMoves:
    def test_deleted_upgraded_to_cross_space(self) -> None:
        events = [
            SyncEvent(kind=EventKind.DELETED, page_id="100", current_path="test.md"),
        ]
        result = mark_cross_space_moves(events, {"100"}, dest_space_keys={"100": "ARCH"})
        assert result[0].kind == EventKind.CROSS_SPACE_MOVE
        assert "ARCH" in result[0].note

    def test_non_cross_space_deleted_unchanged(self) -> None:
        events = [
            SyncEvent(kind=EventKind.DELETED, page_id="200", current_path="other.md"),
        ]
        result = mark_cross_space_moves(events, {"100"})
        assert result[0].kind == EventKind.DELETED

    def test_non_deleted_events_unchanged(self) -> None:
        events = [
            SyncEvent(kind=EventKind.NEW, page_id="100"),
            SyncEvent(kind=EventKind.DELETED, page_id="100", current_path="test.md"),
        ]
        result = mark_cross_space_moves(events, {"100"})
        assert result[0].kind == EventKind.NEW
        assert result[1].kind == EventKind.CROSS_SPACE_MOVE


class TestMarkConflicts:
    def test_content_edit_with_local_edit_is_conflict(self) -> None:
        events = [
            SyncEvent(
                kind=EventKind.CONTENT_EDIT,
                page_id="100",
                current_path="test.md",
                current_version=5,
            )
        ]
        result = mark_conflicts(events, {"100"})
        assert result[0].kind == EventKind.CONFLICT
        assert "local and remote both edited" in result[0].note

    def test_content_edit_without_local_edit_unchanged(self) -> None:
        events = [
            SyncEvent(
                kind=EventKind.CONTENT_EDIT,
                page_id="100",
                current_path="test.md",
                current_version=5,
            )
        ]
        result = mark_conflicts(events, set())
        assert result[0].kind == EventKind.CONTENT_EDIT

    def test_other_events_unchanged(self) -> None:
        events = [
            SyncEvent(kind=EventKind.NEW, page_id="100"),
            SyncEvent(kind=EventKind.RENAME, page_id="200"),
        ]
        result = mark_conflicts(events, {"100", "200"})
        assert result[0].kind == EventKind.NEW
        assert result[1].kind == EventKind.RENAME


class TestMultipleEvents:
    def test_multiple_pages_different_events(self) -> None:
        desired = {
            "1": make_desired(page_id="1", title="Renamed"),
            "2": make_desired(page_id="2", version_number=10),
            "3": make_desired(page_id="3"),
        }
        current = {
            "1": make_local(page_id="1", title="Old Name"),
            "2": make_local(page_id="2", version_number=5),
            # "3" only in desired → NEW
            "4": make_local(page_id="4"),  # only in current → DELETED
        }
        events = compute_events(desired, current, [])

        kinds = {e.page_id: e.kind for e in events}
        assert kinds["1"] == EventKind.RENAME
        assert kinds["2"] == EventKind.CONTENT_EDIT
        assert kinds["3"] == EventKind.NEW
        assert kinds["4"] == EventKind.DELETED
