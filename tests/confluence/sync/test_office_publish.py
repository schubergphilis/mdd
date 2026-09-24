"""Tests for the office-publish phase of sync-space."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from mdd.confluence.state import LocalPage, MirrorState
from mdd.confluence.sync._types import SyncSummary
from mdd.confluence.sync.office_publish import run_office_publish

if TYPE_CHECKING:
    from pathlib import Path


def _write_opted_in(path: Path, page_id: str) -> None:
    path.write_text(
        "---\n"
        "confluence:\n"
        f"  page_id: '{page_id}'\n"
        "  version: 999999\n"
        "  publish_office: docx\n"
        "---\n"
        "# Report\n\nBody.\n",
        encoding="utf-8",
    )


def _mirror_with(path: Path, page_id: str) -> MirrorState:
    state = MirrorState()
    state.tracked[page_id] = LocalPage(
        path=path,
        page_id=page_id,
        title="Report",
        parent_id=None,
        status="CURRENT",
        version_number=999999,
        space_key="OTHER",
        space_id="1",
    )
    return state


class TestRunOfficePublishScope:
    def test_page_outside_synced_space_is_skipped(self, tmp_path: Path) -> None:
        # A tracked file naming a page that is not part of the synced space
        # (it survived the deletion phase under --no-delete) must not reach
        # Confluence: no page fetch, no attachment upload, no body update.
        md = tmp_path / "Report.md"
        _write_opted_in(md, "555")
        client = MagicMock()
        summary = SyncSummary()

        with (
            patch("mdd.confluence.sync.office_publish.publish") as publish,
            patch("mdd.confluence.sync.office_publish.update_page") as update_page,
        ):
            run_office_publish(
                client,
                _mirror_with(md, "555"),
                MagicMock(),
                summary,
                desired_ids={"100", "101"},
            )

        client.get_page.assert_not_called()
        client.upload_attachment.assert_not_called()
        client.put_page.assert_not_called()
        publish.assert_not_called()
        update_page.assert_not_called()
        assert summary.office_skipped_outside_space == [f"555: {md}"]
        assert summary.office_uploaded == 0
        assert summary.failures == []

    def test_page_inside_synced_space_is_published(self, tmp_path: Path) -> None:
        md = tmp_path / "Report.md"
        _write_opted_in(md, "100")
        summary = SyncSummary()

        with patch("mdd.confluence.sync.office_publish._office_publish_one") as one:
            run_office_publish(
                MagicMock(),
                _mirror_with(md, "100"),
                MagicMock(),
                summary,
                desired_ids={"100"},
            )

        one.assert_called_once()
        assert one.call_args.args[0] == "100"
        assert one.call_args.args[1] == md
        assert summary.office_skipped_outside_space == []

    def test_not_opted_in_outside_space_is_not_recorded(self, tmp_path: Path) -> None:
        # Files without publish_office are simply not candidates; the
        # outside-space note is only for files that asked to be published.
        md = tmp_path / "Plain.md"
        md.write_text("---\nconfluence:\n  page_id: '555'\n---\n# Plain\n", encoding="utf-8")
        summary = SyncSummary()

        with patch("mdd.confluence.sync.office_publish._office_publish_one") as one:
            run_office_publish(
                MagicMock(), _mirror_with(md, "555"), MagicMock(), summary, desired_ids=set()
            )

        one.assert_not_called()
        assert summary.office_skipped_outside_space == []


class TestSummaryOfficeSkippedSection:
    def test_section_present_when_skipped(self) -> None:
        summary = SyncSummary()
        summary.office_skipped_outside_space.append("555: /m/Report.md")
        msg = summary.format_commit_message("TEST")
        assert "Office publishing skipped (page not in synced space):" in msg
        assert "- 555: /m/Report.md" in msg

    def test_section_absent_when_none_skipped(self) -> None:
        msg = SyncSummary().format_commit_message("TEST")
        assert "Office publishing skipped" not in msg

    def test_skip_does_not_count_as_change(self) -> None:
        summary = SyncSummary()
        summary.office_skipped_outside_space.append("555: /m/Report.md")
        assert not summary.has_changes()
