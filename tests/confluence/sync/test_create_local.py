"""sync-space creates untracked local files only in the synced space."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from mdd.confluence.client import ConfluenceError
from mdd.confluence.config import ConfluenceConfig
from mdd.confluence.sync._types import SyncOptions, SyncSummary
from mdd.confluence.sync.pull import CreateScope, create_local_pages
from mdd.confluence.sync_diff import EventKind, SyncEvent

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_CONFIG = ConfluenceConfig(url="https://example.atlassian.net", username="u", api_token="t")


def _candidate(tmp_path: Path, name: str, space_key: str) -> Path:
    md = tmp_path / name
    md.write_text(
        f"---\nconfluence:\n  space_key: {space_key}\n  parent_id: '42'\n---\n# {md.stem}\n",
        encoding="utf-8",
    )
    return md


def _scope(space_key: str = "MDDTEST", parent_space_id: str = "111") -> CreateScope:
    """A scope for space id ``111`` whose client reports every parent in *parent_space_id*."""
    client = MagicMock()
    client.get_page.return_value = {"id": "42", "spaceId": parent_space_id}
    return CreateScope(client=client, space_key=space_key, space_id="111")


def _new_event(md: Path) -> SyncEvent:
    return SyncEvent(kind=EventKind.NEW, page_id="", current_path=str(md))


class TestCreateLocalPages:
    def test_matching_space_creates_in_synced_space(self, tmp_path: Path) -> None:
        md = _candidate(tmp_path, "a.md", "mddtest")
        summary = SyncSummary()
        with patch("mdd.confluence.sync.pull.create_page", return_value=0) as create:
            create_local_pages([_new_event(md)], _CONFIG, SyncOptions(), summary, scope=_scope())

        create.assert_called_once_with(md, _CONFIG, space_key="MDDTEST")
        assert summary.new_pushed == 1
        assert summary.create_skipped_other_space == []

    def test_other_space_is_skipped_and_reported(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md = _candidate(tmp_path, "x.md", "HR")
        summary = SyncSummary()
        with (
            caplog.at_level(logging.WARNING, logger="mdd.confluence.sync.pull"),
            patch("mdd.confluence.sync.pull.create_page") as create,
        ):
            create_local_pages([_new_event(md)], _CONFIG, SyncOptions(), summary, scope=_scope())

        create.assert_not_called()
        assert summary.new_pushed == 0
        assert summary.failures == []
        assert summary.create_skipped_other_space == [
            "x.md: names space 'HR', synced space is MDDTEST"
        ]
        assert "x.md" in caplog.text
        assert "'HR'" in caplog.text
        assert "MDDTEST" in caplog.text

    def test_read_only_creates_nothing(self, tmp_path: Path) -> None:
        md = _candidate(tmp_path, "a.md", "MDDTEST")
        summary = SyncSummary()
        with patch("mdd.confluence.sync.pull.create_page") as create:
            create_local_pages(
                [_new_event(md)],
                _CONFIG,
                SyncOptions(read_only=True),
                summary,
                scope=_scope(),
            )
        create.assert_not_called()
        assert summary.create_skipped_other_space == []

    def test_failed_create_is_recorded(self, tmp_path: Path) -> None:
        md = _candidate(tmp_path, "a.md", "MDDTEST")
        summary = SyncSummary()
        with patch("mdd.confluence.sync.pull.create_page", return_value=1):
            create_local_pages([_new_event(md)], _CONFIG, SyncOptions(), summary, scope=_scope())
        assert summary.failures == ["create a.md: create_page returned 1"]

    def test_unreadable_file_is_recorded_as_failure(self, tmp_path: Path) -> None:
        missing = tmp_path / "gone.md"
        summary = SyncSummary()
        with patch("mdd.confluence.sync.pull.create_page") as create:
            create_local_pages(
                [_new_event(missing)], _CONFIG, SyncOptions(), summary, scope=_scope()
            )
        create.assert_not_called()
        assert len(summary.failures) == 1
        assert summary.failures[0].startswith("create gone.md:")

    def test_tracked_and_remote_events_are_ignored(self, tmp_path: Path) -> None:
        md = _candidate(tmp_path, "a.md", "MDDTEST")
        events = [
            SyncEvent(kind=EventKind.NEW, page_id="7", current_path=str(md)),
            SyncEvent(kind=EventKind.NEW, page_id="", current_path=None),
        ]
        with patch("mdd.confluence.sync.pull.create_page") as create:
            create_local_pages(events, _CONFIG, SyncOptions(), SyncSummary(), scope=_scope("X"))
        create.assert_not_called()


class TestCreateLocalPagesParent:
    def test_parent_in_other_space_is_skipped(self, tmp_path: Path) -> None:
        md = _candidate(tmp_path, "x.md", "MDDTEST")
        summary = SyncSummary()
        scope = _scope(parent_space_id="999")
        with patch("mdd.confluence.sync.pull.create_page") as create:
            create_local_pages([_new_event(md)], _CONFIG, SyncOptions(), summary, scope=scope)

        create.assert_not_called()
        scope.client.get_page.assert_called_once_with("42")  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        assert summary.failures == []
        assert summary.create_skipped_other_space == [
            "x.md: parent '42' is not in the synced space MDDTEST"
        ]

    def test_parent_folder_in_synced_space_is_accepted(self, tmp_path: Path) -> None:
        md = _candidate(tmp_path, "a.md", "MDDTEST")
        client = MagicMock()
        client.get_page.side_effect = ConfluenceError("404")
        client.get_folder.return_value = {"id": "42", "spaceId": "111"}
        scope = CreateScope(client=client, space_key="MDDTEST", space_id="111")
        summary = SyncSummary()
        with patch("mdd.confluence.sync.pull.create_page", return_value=0) as create:
            create_local_pages([_new_event(md)], _CONFIG, SyncOptions(), summary, scope=scope)

        create.assert_called_once_with(md, _CONFIG, space_key="MDDTEST")
        assert summary.create_skipped_other_space == []

    def test_parent_that_cannot_be_found_is_skipped(self, tmp_path: Path) -> None:
        md = _candidate(tmp_path, "a.md", "MDDTEST")
        client = MagicMock()
        client.get_page.side_effect = ConfluenceError("404")
        client.get_folder.side_effect = ConfluenceError("404")
        scope = CreateScope(client=client, space_key="MDDTEST", space_id="111")
        summary = SyncSummary()
        with patch("mdd.confluence.sync.pull.create_page") as create:
            create_local_pages([_new_event(md)], _CONFIG, SyncOptions(), summary, scope=scope)

        create.assert_not_called()
        assert summary.create_skipped_other_space == [
            "a.md: parent '42' is not in the synced space MDDTEST"
        ]

    def test_no_parent_needs_no_lookup(self, tmp_path: Path) -> None:
        md = tmp_path / "a.md"
        md.write_text("---\nconfluence:\n  space_key: MDDTEST\n---\n# a\n", encoding="utf-8")
        scope = _scope()
        summary = SyncSummary()
        with patch("mdd.confluence.sync.pull.create_page", return_value=0) as create:
            create_local_pages([_new_event(md)], _CONFIG, SyncOptions(), summary, scope=scope)

        create.assert_called_once_with(md, _CONFIG, space_key="MDDTEST")
        scope.client.get_page.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


class TestSummaryCreateSkippedSection:
    def test_section_present_when_skipped(self) -> None:
        summary = SyncSummary()
        summary.create_skipped_other_space.append("x.md: names space HR, synced space is TEST")
        msg = summary.format_commit_message("TEST")
        assert "New pages not created (file names another space):" in msg
        assert "- x.md: names space HR, synced space is TEST" in msg

    def test_section_absent_when_none_skipped(self) -> None:
        assert "New pages not created" not in SyncSummary().format_commit_message("TEST")

    def test_skip_does_not_count_as_change(self) -> None:
        summary = SyncSummary()
        summary.create_skipped_other_space.append("x.md: names space HR, synced space is TEST")
        assert not summary.has_changes()
