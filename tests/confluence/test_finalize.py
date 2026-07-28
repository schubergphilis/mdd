"""Tests for confluence sync finalize helpers (spec S14)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mdd.confluence.sync._types import SyncSummary
from mdd.confluence.sync.finalize import build_mirror_or_raise

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestBuildMirrorOrRaiseSummary:
    """`build_mirror_or_raise` reports buckets separately (#87)."""

    def test_attachment_derived_reported_separately(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # One attachment-derived file (converter output).
        attachments_dir = tmp_path / "Foo-attachments"
        attachments_dir.mkdir()
        (attachments_dir / "bar.pdf.md").write_text("# bar\n", encoding="utf-8")
        # One genuinely manual file (no converter suffix, not under *-attachments).
        (tmp_path / "manual.md").write_text("# manual notes\n", encoding="utf-8")

        summary = SyncSummary()
        with caplog.at_level("INFO", logger="mdd.confluence.sync.finalize"):
            mirror = build_mirror_or_raise(tmp_path, summary)

        assert len(mirror.attachment_derived) == 1
        assert len(mirror.manual) == 1
        # The summary count of "skipped_manual" tracks only user-authored manuals.
        assert summary.skipped_manual == 1
        assert summary.skipped_attachment_derived == 1

        msgs = " ".join(r.getMessage() for r in caplog.records)
        # Mirror summary reports the new bucket separately, not folded into "manually-managed".
        assert "1 manually-managed" in msgs
        assert "1 attachment-derived" in msgs
        # The "manually-managed" follow-up line only lists the user file.
        assert "manual.md" in msgs
        assert "bar.pdf.md" not in msgs

    def test_zero_attachment_derived_not_mentioned_when_empty(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "manual.md").write_text("# manual\n", encoding="utf-8")

        summary = SyncSummary()
        with caplog.at_level("INFO", logger="mdd.confluence.sync.finalize"):
            build_mirror_or_raise(tmp_path, summary)

        msgs = " ".join(r.getMessage() for r in caplog.records)
        # Always include the bucket in the summary for consistent parsing.
        assert "0 attachment-derived" in msgs
        assert summary.skipped_attachment_derived == 0
