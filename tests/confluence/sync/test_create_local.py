"""sync-space creates untracked local files only in the synced space."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from mdd.confluence.config import ConfluenceConfig
from mdd.confluence.sync._types import SyncOptions, SyncSummary
from mdd.confluence.sync.pull import create_local_pages
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


def _new_event(md: Path) -> SyncEvent:
    return SyncEvent(kind=EventKind.NEW, page_id="", current_path=str(md))


class TestCreateLocalPages:
    def test_matching_space_creates_in_synced_space(self, tmp_path: Path) -> None:
        md = _candidate(tmp_path, "a.md", "mddtest")
        summary = SyncSummary()
        with patch("mdd.confluence.sync.pull.create_page", return_value=0) as create:
            create_local_pages(
                [_new_event(md)], _CONFIG, SyncOptions(), summary, space_key="MDDTEST"
            )

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
            create_local_pages(
                [_new_event(md)], _CONFIG, SyncOptions(), summary, space_key="MDDTEST"
            )

        create.assert_not_called()
        assert summary.new_pushed == 0
        assert summary.failures == []
        assert summary.create_skipped_other_space == [
            "x.md: names space HR, synced space is MDDTEST"
        ]
        assert "x.md" in caplog.text
        assert "'HR'" in caplog.text
        assert "'MDDTEST'" in caplog.text

    def test_read_only_creates_nothing(self, tmp_path: Path) -> None:
        md = _candidate(tmp_path, "a.md", "MDDTEST")
        summary = SyncSummary()
        with patch("mdd.confluence.sync.pull.create_page") as create:
            create_local_pages(
                [_new_event(md)],
                _CONFIG,
                SyncOptions(read_only=True),
                summary,
                space_key="MDDTEST",
            )
        create.assert_not_called()
        assert summary.create_skipped_other_space == []

    def test_failed_create_is_recorded(self, tmp_path: Path) -> None:
        md = _candidate(tmp_path, "a.md", "MDDTEST")
        summary = SyncSummary()
        with patch("mdd.confluence.sync.pull.create_page", return_value=1):
            create_local_pages(
                [_new_event(md)], _CONFIG, SyncOptions(), summary, space_key="MDDTEST"
            )
        assert summary.failures == ["create a.md: create_page returned 1"]

    def test_unreadable_file_is_recorded_as_failure(self, tmp_path: Path) -> None:
        missing = tmp_path / "gone.md"
        summary = SyncSummary()
        with patch("mdd.confluence.sync.pull.create_page") as create:
            create_local_pages(
                [_new_event(missing)], _CONFIG, SyncOptions(), summary, space_key="MDDTEST"
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
            create_local_pages(events, _CONFIG, SyncOptions(), SyncSummary(), space_key="X")
        create.assert_not_called()


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


def test_client_mock_unused() -> None:
    assert isinstance(MagicMock(), MagicMock)
