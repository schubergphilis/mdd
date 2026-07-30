"""Tests for mdd.sharepoint.diff — pure pair classification."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mdd.sharepoint.diff import (
    _EMPTY_SYNC_STATE,  # pyright: ignore[reportPrivateUsage]
    PairAction,
    SyncState,
    _word_lock_path,  # pyright: ignore[reportPrivateUsage]
    classify_pair,
    read_sync_state,
    sha256_file,
)

if TYPE_CHECKING:
    import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sync_state(
    docx_sha: str | None = "aabbcc",
    md_sha: str | None = "ddeeff",
    last_sync: str | None = "2026-01-01T00:00:00+00:00",
    converter_version: str | None = "2.4.0",
    *,
    update_office: bool = True,
) -> SyncState:
    """Build a SyncState for tests. ``update_office`` defaults to True so the
    existing diff-table tests exercise the live MD_TO_DOCX / DIVERGED paths;
    pass ``update_office=False`` to exercise the SKIP_MD_UPDATE gate."""
    return SyncState(
        office_sha256_at_sync=docx_sha,
        md_sha256_at_sync=md_sha,
        last_sync=last_sync,
        converter_version=converter_version,
        update_office=update_office,
    )


# ---------------------------------------------------------------------------
# sha256_file
# ---------------------------------------------------------------------------


class TestSha256File:
    def test_known_content(self, tmp_path: Path) -> None:
        import hashlib

        content = b"hello world"
        f = tmp_path / "f.txt"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert sha256_file(f) == expected

    def test_empty_file(self, tmp_path: Path) -> None:
        import hashlib

        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert sha256_file(f) == expected

    def test_different_files_differ(self, tmp_path: Path) -> None:
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_bytes(b"aaa")
        b.write_bytes(b"bbb")
        assert sha256_file(a) != sha256_file(b)


# ---------------------------------------------------------------------------
# _word_lock_path
# ---------------------------------------------------------------------------


class TestWordLockPath:
    def test_standard_path(self) -> None:
        p = _word_lock_path(Path("/some/dir/Foo.docx"))
        assert p.name == "~$Foo.docx"
        assert p.parent == Path("/some/dir")

    def test_pptx_path(self) -> None:
        p = _word_lock_path(Path("Slides.pptx"))
        assert p.name == "~$Slides.pptx"


# ---------------------------------------------------------------------------
# read_sync_state
# ---------------------------------------------------------------------------


class TestReadSyncState:
    def test_no_file_returns_empty(self, tmp_path: Path) -> None:
        result = read_sync_state(tmp_path / "nonexistent.md")
        assert result == _EMPTY_SYNC_STATE

    def test_no_frontmatter_returns_empty(self, tmp_path: Path) -> None:
        md = tmp_path / "notes.md"
        md.write_text("# Just a heading\n", encoding="utf-8")
        result = read_sync_state(md)
        assert result == _EMPTY_SYNC_STATE

    def test_frontmatter_without_sync_block_returns_empty(self, tmp_path: Path) -> None:
        md = tmp_path / "notes.md"
        md.write_text(
            "---\nsharepoint:\n  site: MySite\n---\n# Body\n",
            encoding="utf-8",
        )
        result = read_sync_state(md)
        assert result == _EMPTY_SYNC_STATE

    def test_reads_sync_block(self, tmp_path: Path) -> None:
        md = tmp_path / "report.docx.md"
        md.write_text(
            "---\n"
            "sharepoint:\n"
            "  site: MySite\n"
            "  sync:\n"
            "    office_sha256_at_sync: aabbcc\n"
            "    md_sha256_at_sync: ddeeff\n"
            "    last_sync: '2026-01-01T00:00:00+00:00'\n"
            "    converter_version: '2.4.0'\n"
            "    update_office: true\n"
            "---\n# Body\n",
            encoding="utf-8",
        )
        result = read_sync_state(md)
        assert result.office_sha256_at_sync == "aabbcc"
        assert result.md_sha256_at_sync == "ddeeff"
        assert result.last_sync == "2026-01-01T00:00:00+00:00"
        assert result.converter_version == "2.4.0"
        assert result.update_office is True

    def test_update_office_defaults_to_false(self, tmp_path: Path) -> None:
        md = tmp_path / "report.docx.md"
        md.write_text(
            "---\n"
            "sharepoint:\n"
            "  sync:\n"
            "    office_sha256_at_sync: aa\n"
            "    md_sha256_at_sync: bb\n"
            "---\n# Body\n",
            encoding="utf-8",
        )
        result = read_sync_state(md)
        assert result.update_office is False

    def test_invalid_yaml_returns_empty(self, tmp_path: Path) -> None:
        md = tmp_path / "broken.md"
        md.write_text("---\n: invalid:\n  yaml: :\n---\nbody\n", encoding="utf-8")
        result = read_sync_state(md)
        assert result == _EMPTY_SYNC_STATE

    def test_unknown_sharepoint_key_logs_and_returns_empty(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # An unknown key in the sharepoint block triggers a
        # ValidationError, which surfaces as a logged warning plus an
        # empty sync state rather than a silent fallthrough.
        md = tmp_path / "typo.md"
        md.write_text(
            "---\nsharepoint:\n  souce_path: Foo.docx\n---\n# body\n",
            encoding="utf-8",
        )
        with caplog.at_level("WARNING", logger="mdd.sharepoint.diff"):
            result = read_sync_state(md)
        assert result == _EMPTY_SYNC_STATE
        assert any("souce_path" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# classify_pair
# ---------------------------------------------------------------------------


class TestClassifyPairWordLocked:
    def test_word_lock_detected(self, tmp_path: Path) -> None:
        docx = tmp_path / "Foo.docx"
        docx.write_bytes(b"fake docx")
        lock = tmp_path / "~$Foo.docx"
        lock.write_bytes(b"lock")
        md = tmp_path / "Foo.docx.md"
        md.write_text("---\nsharepoint:\n  site: S\n---\n# body\n", encoding="utf-8")

        action = classify_pair(docx, md, sync_state=_EMPTY_SYNC_STATE)
        assert action == PairAction.WORD_LOCKED

    def test_word_lock_takes_priority_over_sync_block(self, tmp_path: Path) -> None:
        """Word lock trumps even a fully valid sync block."""
        content = b"docx data"
        docx = tmp_path / "Report.docx"
        docx.write_bytes(content)
        (tmp_path / "~$Report.docx").write_bytes(b"")

        import hashlib

        docx_sha = hashlib.sha256(content).hexdigest()
        md = tmp_path / "Report.docx.md"
        md_text = "# body"
        md.write_text(md_text, encoding="utf-8")
        md_sha = hashlib.sha256(md_text.encode()).hexdigest()

        sync_state = _sync_state(docx_sha=docx_sha, md_sha=md_sha)
        action = classify_pair(docx, md, sync_state=sync_state)
        assert action == PairAction.WORD_LOCKED


class TestClassifyPairMissingFiles:
    def test_neither_file_is_noop(self) -> None:
        action = classify_pair(None, None, sync_state=_EMPTY_SYNC_STATE)
        assert action == PairAction.NO_OP

    def test_docx_only(self, tmp_path: Path) -> None:
        docx = tmp_path / "Foo.docx"
        docx.write_bytes(b"x")
        action = classify_pair(docx, None, sync_state=_EMPTY_SYNC_STATE)
        assert action == PairAction.FIRST_SYNC_DOCX_AUTHORITATIVE

    def test_md_only_orphaned(self, tmp_path: Path) -> None:
        md = tmp_path / "Foo.docx.md"
        md.write_text("# body", encoding="utf-8")
        action = classify_pair(None, md, sync_state=_EMPTY_SYNC_STATE)
        assert action == PairAction.FIRST_SYNC_MD_AUTHORITATIVE


class TestClassifyPairFirstSync:
    def test_both_present_no_sync_block_docx_wins(self, tmp_path: Path) -> None:
        docx = tmp_path / "Foo.docx"
        docx.write_bytes(b"docx")
        md = tmp_path / "Foo.docx.md"
        md.write_text("# old content", encoding="utf-8")
        action = classify_pair(docx, md, sync_state=_EMPTY_SYNC_STATE)
        assert action == PairAction.FIRST_SYNC_BOTH_DOCX_WINS


class TestClassifyPairDiffTable:
    """Tests for the office/markdown reconciliation diff table."""

    def _make_pair(
        self, tmp_path: Path, *, docx_content: bytes, md_content: str
    ) -> tuple[Path, Path, SyncState]:
        import hashlib

        docx = tmp_path / "Report.docx"
        docx.write_bytes(docx_content)
        md = tmp_path / "Report.docx.md"
        md.write_text(md_content, encoding="utf-8")

        docx_sha = hashlib.sha256(docx_content).hexdigest()
        md_sha = hashlib.sha256(md_content.encode()).hexdigest()
        sync_state = _sync_state(docx_sha=docx_sha, md_sha=md_sha)
        return docx, md, sync_state

    def test_both_unchanged_is_noop(self, tmp_path: Path) -> None:
        docx_content = b"original docx"
        md_content = "# Original markdown"
        docx, md, sync_state = self._make_pair(
            tmp_path, docx_content=docx_content, md_content=md_content
        )
        action = classify_pair(docx, md, sync_state=sync_state)
        assert action == PairAction.NO_OP

    def test_docx_changed_md_unchanged_is_docx_to_md(self, tmp_path: Path) -> None:
        import hashlib

        docx = tmp_path / "Report.docx"
        md = tmp_path / "Report.docx.md"

        old_docx = b"old docx"
        md_content = "# Markdown content"

        # Set sync state to old values
        md_sha = hashlib.sha256(md_content.encode()).hexdigest()
        sync_state = _sync_state(
            docx_sha=hashlib.sha256(old_docx).hexdigest(),
            md_sha=md_sha,
        )

        # Write NEW docx content (changed)
        docx.write_bytes(b"new docx content")
        md.write_text(md_content, encoding="utf-8")

        action = classify_pair(docx, md, sync_state=sync_state)
        assert action == PairAction.DOCX_TO_MD

    def test_md_changed_docx_unchanged_is_md_to_docx(self, tmp_path: Path) -> None:
        import hashlib

        docx = tmp_path / "Report.docx"
        md = tmp_path / "Report.docx.md"

        docx_content = b"original docx"
        old_md = "# Old markdown"

        docx_sha = hashlib.sha256(docx_content).hexdigest()
        sync_state = _sync_state(
            docx_sha=docx_sha,
            md_sha=hashlib.sha256(old_md.encode()).hexdigest(),
        )

        # Write NEW md content (changed)
        docx.write_bytes(docx_content)
        md.write_text("# NEW markdown content changed", encoding="utf-8")

        action = classify_pair(docx, md, sync_state=sync_state)
        assert action == PairAction.MD_TO_DOCX

    def test_both_changed_is_diverged(self, tmp_path: Path) -> None:
        import hashlib

        docx = tmp_path / "Report.docx"
        md = tmp_path / "Report.docx.md"

        old_docx = b"old docx"
        old_md = "# Old markdown"

        sync_state = _sync_state(
            docx_sha=hashlib.sha256(old_docx).hexdigest(),
            md_sha=hashlib.sha256(old_md.encode()).hexdigest(),
        )

        # Both now differ from sync state
        docx.write_bytes(b"NEW docx content")
        md.write_text("# NEW markdown", encoding="utf-8")

        action = classify_pair(docx, md, sync_state=sync_state)
        assert action == PairAction.DIVERGED

    def test_docx_nonexistent_with_sync_block_is_first_sync_md(self, tmp_path: Path) -> None:
        md = tmp_path / "Report.docx.md"
        md.write_text("# content", encoding="utf-8")
        # Even with a non-empty sync state, missing docx → first_sync_md
        action = classify_pair(None, md, sync_state=_sync_state())
        assert action == PairAction.FIRST_SYNC_MD_AUTHORITATIVE


class TestClassifyPairUpdateOfficeGate:
    """update_office gates md→office rendering.

    When False (the default), any md edit must surface as SKIP_MD_UPDATE
    instead of MD_TO_DOCX or DIVERGED, so office files don't get clobbered
    by inferior Quarto renders.
    """

    def test_md_changed_skipped_when_update_office_false(self, tmp_path: Path) -> None:
        import hashlib

        docx_content = b"original docx"
        old_md = "# Old"

        docx = tmp_path / "Report.docx"
        md = tmp_path / "Report.docx.md"
        docx.write_bytes(docx_content)
        md.write_text("# NEW", encoding="utf-8")

        sync_state = _sync_state(
            docx_sha=hashlib.sha256(docx_content).hexdigest(),
            md_sha=hashlib.sha256(old_md.encode()).hexdigest(),
            update_office=False,
        )
        action = classify_pair(docx, md, sync_state=sync_state)
        assert action == PairAction.SKIP_MD_UPDATE

    def test_both_changed_skipped_when_update_office_false(self, tmp_path: Path) -> None:
        import hashlib

        docx = tmp_path / "Report.docx"
        md = tmp_path / "Report.docx.md"
        docx.write_bytes(b"new docx")
        md.write_text("# new md", encoding="utf-8")

        sync_state = _sync_state(
            docx_sha=hashlib.sha256(b"old docx").hexdigest(),
            md_sha=hashlib.sha256(b"# old md").hexdigest(),
            update_office=False,
        )
        action = classify_pair(docx, md, sync_state=sync_state)
        assert action == PairAction.SKIP_MD_UPDATE

    def test_docx_changed_md_unchanged_runs_regardless(self, tmp_path: Path) -> None:
        import hashlib

        # md_now is computed via sha256_md_content (canonical form) so for a
        # frontmatter-less file it equals plain sha256 of the bytes.
        md_text = "# md"
        docx = tmp_path / "Report.docx"
        md = tmp_path / "Report.docx.md"
        docx.write_bytes(b"NEW docx")
        md.write_text(md_text, encoding="utf-8")

        sync_state = _sync_state(
            docx_sha=hashlib.sha256(b"old docx").hexdigest(),
            md_sha=hashlib.sha256(md_text.encode()).hexdigest(),
            update_office=False,
        )
        action = classify_pair(docx, md, sync_state=sync_state)
        assert action == PairAction.DOCX_TO_MD
