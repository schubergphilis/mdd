"""Tests for SyncSummary's restriction-check-unverified reporting."""

from __future__ import annotations

from mdd.confluence.sync._types import SyncSummary


class TestRestrictionCheckUnverified:
    def test_omitted_when_zero(self) -> None:
        summary = SyncSummary(content_pushed=1)
        msg = summary.format_commit_message("ENG")
        assert "Restriction check unverified" not in msg

    def test_included_with_count_when_nonzero(self) -> None:
        summary = SyncSummary(content_pushed=1, restriction_check_unverified=3)
        msg = summary.format_commit_message("ENG")
        assert "Restriction check unverified:" in msg
        assert "3 pages pushed without confirming update permission" in msg

    def test_does_not_count_as_a_change(self) -> None:
        """An unverified check by itself isn't a mutation the summary reports as 'changed'."""
        summary = SyncSummary(restriction_check_unverified=5)
        assert summary.has_changes() is False
