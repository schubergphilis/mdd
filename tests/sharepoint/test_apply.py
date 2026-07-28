"""Tests for mdd.sharepoint.apply — atomic apply layer."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from mdd.sharepoint.apply import (
    SyncRunSummary,
    apply_diverged,
    apply_first_sync_docx,
    apply_first_sync_md,
    backup_office_file,
    print_dry_run_plan,
)
from mdd.sharepoint.apply.actions import (
    _strip_frontmatter,  # pyright: ignore[reportPrivateUsage]
)
from mdd.sharepoint.apply.git import (
    _build_commit_message,  # pyright: ignore[reportPrivateUsage]
)
from mdd.sharepoint.apply.io import atomic_write_bytes, atomic_write_text
from mdd.sharepoint.apply.sync_block import (
    _inject_sync_block,  # pyright: ignore[reportPrivateUsage]
)

# Backwards-compatible aliases for tests written against the pre-split names.
_atomic_write_bytes = atomic_write_bytes
_atomic_write_text = atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

# ---------------------------------------------------------------------------
# Atomic write helpers
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_write_bytes_creates_file(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.bin"
        _atomic_write_bytes(dest, b"hello")
        assert dest.read_bytes() == b"hello"

    def test_write_bytes_no_tmp_left(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.bin"
        _atomic_write_bytes(dest, b"hello")
        assert not (tmp_path / "out.bin.tmp").exists()

    def test_write_text_creates_file(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.md"
        _atomic_write_text(dest, "# Hello")
        assert dest.read_text(encoding="utf-8") == "# Hello"

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        dest = tmp_path / "sub" / "deep" / "out.md"
        _atomic_write_text(dest, "content")
        assert dest.exists()

    def test_write_overwrites_existing(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.md"
        dest.write_text("old", encoding="utf-8")
        _atomic_write_text(dest, "new")
        assert dest.read_text(encoding="utf-8") == "new"


# ---------------------------------------------------------------------------
# Backup helper
# ---------------------------------------------------------------------------


class TestBackupOfficeFile:
    def test_creates_backup(self, tmp_path: Path) -> None:
        site_root = tmp_path / "site"
        site_root.mkdir()
        office = site_root / "Report.docx"
        office.write_bytes(b"docx data")

        backup_office_file(office, site_root)

        backups = list((site_root / ".mdd-backups").rglob("*Report.docx"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == b"docx data"

    def test_backup_filename_has_timestamp(self, tmp_path: Path) -> None:
        site_root = tmp_path / "site"
        site_root.mkdir()
        office = site_root / "Foo.docx"
        office.write_bytes(b"x")

        backup_office_file(office, site_root)

        # Backup file name should start with a timestamp
        backups = list((site_root / ".mdd-backups").rglob("*Foo.docx"))
        assert len(backups) == 1
        name = backups[0].name
        # Timestamp format: YYYYMMDDTHHMMSS-Foo.docx
        assert name.endswith("-Foo.docx")

    def test_backup_with_path_outside_root(self, tmp_path: Path) -> None:
        """If the office file is outside output_root, backup still works."""
        site_root = tmp_path / "site"
        site_root.mkdir()
        external = tmp_path / "external.docx"
        external.write_bytes(b"x")

        # Should not raise
        backup_office_file(external, site_root)


# ---------------------------------------------------------------------------
# _inject_sync_block
# ---------------------------------------------------------------------------


class TestInjectSyncBlock:
    def _new_sync(self) -> dict[str, object]:
        return {
            "office_sha256_at_sync": "aabb",
            "md_sha256_at_sync": "ccdd",
            "last_sync": "2026-01-01T00:00:00+00:00",
            "converter": "docling-docx",
            "converter_version": "2.4.0",
            "update_office": False,
        }

    def test_injects_into_empty_text(self) -> None:
        text = "# body\n"
        result = _inject_sync_block(text, self._new_sync())
        assert "sharepoint:" in result
        assert "sync:" in result
        assert "office_sha256_at_sync: aabb" in result

    def test_injects_into_existing_sharepoint_frontmatter(self) -> None:
        text = "---\nsharepoint:\n  site: MySite\n---\n# body\n"
        result = _inject_sync_block(text, self._new_sync())
        assert "site: MySite" in result
        assert "office_sha256_at_sync: aabb" in result

    def test_injects_into_non_sharepoint_frontmatter(self) -> None:
        text = "---\ntitle: My Doc\nauthor: Leo\n---\n# body\n"
        result = _inject_sync_block(text, self._new_sync())
        assert "title: My Doc" in result
        assert "author: Leo" in result
        assert "office_sha256_at_sync: aabb" in result

    def test_preserves_body(self) -> None:
        text = "---\nsharepoint:\n  site: S\n---\n# Original Body\n\nWith content.\n"
        result = _inject_sync_block(text, self._new_sync())
        assert "# Original Body" in result
        assert "With content." in result


# ---------------------------------------------------------------------------
# _strip_frontmatter
# ---------------------------------------------------------------------------


class TestStripFrontmatter:
    def test_strips_frontmatter(self) -> None:
        text = "---\nkey: val\n---\n# body\n"
        assert _strip_frontmatter(text) == "# body\n"

    def test_no_frontmatter_unchanged(self) -> None:
        text = "# heading\n"
        assert _strip_frontmatter(text) == text

    def test_unclosed_frontmatter_unchanged(self) -> None:
        text = "---\nkey: val\nno closing fence"
        assert _strip_frontmatter(text) == text


# ---------------------------------------------------------------------------
# apply_docx_to_md
# ---------------------------------------------------------------------------


class TestApplyDocxToMd:
    def test_preserves_existing_update_office_true(self, tmp_path: Path) -> None:
        """Regression: a docx→md restamp must not silently flip update_office.

        Scenario: the user opted into bidirectional sync by setting
        ``update_office: true``. Later, the docx changes (e.g. someone edited
        it in Word). DOCX_TO_MD fires; the .md is regenerated. The
        update_office flag must stay true so future md edits still render.
        """
        from mdd.sharepoint.apply.actions import apply_docx_to_md
        from mdd.sharepoint.diff import read_sync_state

        docx = tmp_path / "Report.docx"
        docx.write_bytes(b"new docx body")
        md = tmp_path / "Report.docx.md"
        md.write_text(
            "---\n"
            "sharepoint:\n"
            "  sync:\n"
            "    office_sha256_at_sync: oldoffice\n"
            "    md_sha256_at_sync: oldmd\n"
            "    update_office: true\n"
            "---\n# old body\n",
            encoding="utf-8",
        )

        def fake_convert(s: Path, d: Path) -> None:
            d.parent.mkdir(parents=True, exist_ok=True)
            d.write_text("# regenerated\n", encoding="utf-8")

        def convert_wrapper(s: Path, d: Path) -> str:
            fake_convert(s, d)
            return "docling-docx"

        with patch("mdd.sharepoint.apply.actions.do_convert", side_effect=convert_wrapper):
            apply_docx_to_md(docx, md)

        assert read_sync_state(md).update_office is True

    def test_preserves_existing_update_office_false(self, tmp_path: Path) -> None:
        """Symmetric case: ``update_office: false`` stays false across a docx→md restamp."""
        from mdd.sharepoint.apply.actions import apply_docx_to_md
        from mdd.sharepoint.diff import read_sync_state

        docx = tmp_path / "Report.docx"
        docx.write_bytes(b"new docx body")
        md = tmp_path / "Report.docx.md"
        md.write_text(
            "---\n"
            "sharepoint:\n"
            "  sync:\n"
            "    office_sha256_at_sync: oldoffice\n"
            "    md_sha256_at_sync: oldmd\n"
            "    update_office: false\n"
            "---\n# old body\n",
            encoding="utf-8",
        )

        def fake_convert(s: Path, d: Path) -> None:
            d.write_text("# regenerated\n", encoding="utf-8")

        def convert_wrapper(s: Path, d: Path) -> str:
            fake_convert(s, d)
            return "docling-docx"

        with patch("mdd.sharepoint.apply.actions.do_convert", side_effect=convert_wrapper):
            apply_docx_to_md(docx, md)

        assert read_sync_state(md).update_office is False


# ---------------------------------------------------------------------------
# apply_diverged
# ---------------------------------------------------------------------------


class TestApplyDiverged:
    def test_writes_candidate_file(self, tmp_path: Path) -> None:
        docx = tmp_path / "Report.docx"
        docx.write_bytes(b"old docx")
        md = tmp_path / "Report.docx.md"
        md.write_text("# Markdown", encoding="utf-8")

        candidate_data = b"rendered candidate"

        def fake_render(md_path: Path, dest: Path) -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(candidate_data)

        with patch("mdd.sharepoint.apply.actions.do_render", side_effect=fake_render):
            result = apply_diverged(docx, md, last_sync="2026-01-01T00:00:00+00:00")

        candidate = tmp_path / "Report.from-md.docx"
        assert candidate.exists()
        assert candidate.read_bytes() == candidate_data
        assert result.divergence_candidate == candidate
        assert result.warning is not None
        assert "Report.docx" in result.warning
        assert "2026-01-01" in result.warning

    def test_leaves_sources_untouched(self, tmp_path: Path) -> None:
        docx = tmp_path / "Foo.docx"
        docx_data = b"original docx"
        docx.write_bytes(docx_data)
        md = tmp_path / "Foo.docx.md"
        md_text = "# Original markdown"
        md.write_text(md_text, encoding="utf-8")

        def fake_render(md_path: Path, dest: Path) -> None:
            dest.write_bytes(b"candidate")

        with patch("mdd.sharepoint.apply.actions.do_render", side_effect=fake_render):
            apply_diverged(docx, md)

        # Sources unchanged
        assert docx.read_bytes() == docx_data
        assert md.read_text(encoding="utf-8") == md_text

    def test_skips_rerender_if_candidate_exists(self, tmp_path: Path) -> None:
        """If .from-md.docx already exists, skip re-render."""
        docx = tmp_path / "Report.docx"
        docx.write_bytes(b"docx")
        md = tmp_path / "Report.docx.md"
        md.write_text("# md", encoding="utf-8")
        candidate = tmp_path / "Report.from-md.docx"
        candidate.write_bytes(b"existing candidate")

        mock_render = MagicMock()
        with patch("mdd.sharepoint.apply.actions.do_render", mock_render):
            result = apply_diverged(docx, md)

        mock_render.assert_not_called()
        assert result.divergence_candidate == candidate
        warning_lower = (result.warning or "").lower()
        assert "existing" in warning_lower or "exists" in warning_lower

    def test_no_tmp_file_left_after_render(self, tmp_path: Path) -> None:
        docx = tmp_path / "Report.docx"
        docx.write_bytes(b"docx")
        md = tmp_path / "Report.docx.md"
        md.write_text("# md", encoding="utf-8")

        def fake_render(md_path: Path, dest: Path) -> None:
            dest.write_bytes(b"rendered")

        with patch("mdd.sharepoint.apply.actions.do_render", side_effect=fake_render):
            apply_diverged(docx, md)

        # No temp file should remain
        assert not list(tmp_path.glob("*.tmp"))

    def test_render_dest_keeps_office_suffix(self, tmp_path: Path) -> None:
        """Regression: the temp path handed to do_render must keep ``.docx``/``.pptx``.

        ``reverse_for(dest.suffix)`` dispatches on the destination suffix, and
        Quarto infers output format from the extension — a ``.tmp`` suffix
        breaks both.
        """
        docx = tmp_path / "Report.docx"
        docx.write_bytes(b"docx")
        md = tmp_path / "Report.docx.md"
        md.write_text("# md", encoding="utf-8")

        captured: list[Path] = []

        def fake_render(md_path: Path, dest: Path) -> None:
            captured.append(dest)
            dest.write_bytes(b"rendered")

        with patch("mdd.sharepoint.apply.actions.do_render", side_effect=fake_render):
            apply_diverged(docx, md)

        assert captured, "do_render was not invoked"
        assert captured[0].suffix == ".docx"

    def test_pptx_candidate_name(self, tmp_path: Path) -> None:
        pptx = tmp_path / "Deck.pptx"
        pptx.write_bytes(b"pptx")
        md = tmp_path / "Deck.pptx.md"
        md.write_text("# slides", encoding="utf-8")

        def fake_render(md_path: Path, dest: Path) -> None:
            dest.write_bytes(b"rendered pptx")

        with patch("mdd.sharepoint.apply.actions.do_render", side_effect=fake_render):
            result = apply_diverged(pptx, md)

        candidate = tmp_path / "Deck.from-md.pptx"
        assert candidate.exists()
        assert result.divergence_candidate == candidate


# ---------------------------------------------------------------------------
# apply_first_sync_docx
# ---------------------------------------------------------------------------


class TestApplyFirstSyncDocx:
    def test_converts_and_stamps_sync_block(self, tmp_path: Path) -> None:
        docx = tmp_path / "Foo.docx"
        docx.write_bytes(b"fake docx")
        md = tmp_path / "Foo.docx.md"

        def fake_convert(src: Path, dest: Path) -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("# Converted", encoding="utf-8")

        def convert_wrapper(s: Path, d: Path) -> str:
            fake_convert(s, d)
            return "docling-docx"

        with patch("mdd.sharepoint.apply.actions.do_convert", side_effect=convert_wrapper):
            apply_first_sync_docx(docx, md)

        assert md.exists()
        content = md.read_text(encoding="utf-8")
        assert "sync:" in content
        assert "office_sha256_at_sync:" in content
        assert "md_sha256_at_sync:" in content

    def test_no_tmp_left(self, tmp_path: Path) -> None:
        docx = tmp_path / "Foo.docx"
        docx.write_bytes(b"fake")
        md = tmp_path / "Foo.docx.md"

        def fake_convert(src: Path, dest: Path) -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("# Converted", encoding="utf-8")

        def convert_wrapper(s: Path, d: Path) -> str:
            fake_convert(s, d)
            return "x"

        with patch("mdd.sharepoint.apply.actions.do_convert", side_effect=convert_wrapper):
            apply_first_sync_docx(docx, md)

        assert not list(tmp_path.glob("*.tmp"))

    def test_resync_after_first_sync_is_noop(self, tmp_path: Path) -> None:
        """Regression: after first-sync(docx→md), a follow-up sync must classify NO_OP.

        Previously the stored md_sha256_at_sync was captured before the sync
        block was injected into the file, so every subsequent sync saw the on-
        disk hash as drifted and re-rendered md→docx forever.
        """
        from mdd.sharepoint.diff import PairAction, classify_pair, read_sync_state

        docx = tmp_path / "Foo.docx"
        docx.write_bytes(b"fake docx")
        md = tmp_path / "Foo.docx.md"

        def fake_convert(src: Path, dest: Path) -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("# Converted\n", encoding="utf-8")

        def convert_wrapper(s: Path, d: Path) -> str:
            fake_convert(s, d)
            return "docling-docx"

        with patch("mdd.sharepoint.apply.actions.do_convert", side_effect=convert_wrapper):
            apply_first_sync_docx(docx, md)

        # Neither the .docx nor the .md was edited; classify_pair must say NO_OP.
        action = classify_pair(docx, md, sync_state=read_sync_state(md))
        assert action == PairAction.NO_OP


# ---------------------------------------------------------------------------
# apply_first_sync_md
# ---------------------------------------------------------------------------


class TestApplyFirstSyncMd:
    def test_renders_and_stamps_sync_block(self, tmp_path: Path) -> None:
        md = tmp_path / "Notes.docx.md"
        md.write_text("# Notes content", encoding="utf-8")
        docx = tmp_path / "Notes.docx"

        def fake_render(md_path: Path, dest: Path) -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"rendered docx")

        with patch("mdd.sharepoint.apply.actions.do_render", side_effect=fake_render):
            apply_first_sync_md(docx, md)

        assert docx.exists()
        assert docx.read_bytes() == b"rendered docx"

        content = md.read_text(encoding="utf-8")
        assert "sync:" in content
        assert "quarto-docx" in content

    def test_backup_called_when_docx_exists(self, tmp_path: Path) -> None:
        md = tmp_path / "Foo.docx.md"
        md.write_text("# content", encoding="utf-8")
        docx = tmp_path / "Foo.docx"
        docx.write_bytes(b"old docx")

        def fake_render(md_path: Path, dest: Path) -> None:
            dest.write_bytes(b"new")

        mock_backup = MagicMock()
        with (
            patch("mdd.sharepoint.apply.actions.do_render", side_effect=fake_render),
            patch("mdd.sharepoint.apply.actions.backup_office_file", mock_backup),
        ):
            apply_first_sync_md(docx, md, backup=True, output_root=tmp_path)

        mock_backup.assert_called_once_with(docx, tmp_path)

    def test_no_tmp_left(self, tmp_path: Path) -> None:
        md = tmp_path / "Foo.docx.md"
        md.write_text("# content", encoding="utf-8")
        docx = tmp_path / "Foo.docx"

        def fake_render(md_path: Path, dest: Path) -> None:
            dest.write_bytes(b"rendered")

        with patch("mdd.sharepoint.apply.actions.do_render", side_effect=fake_render):
            apply_first_sync_md(docx, md)

        assert not list(tmp_path.glob("*.tmp"))

    def test_render_dest_keeps_office_suffix(self, tmp_path: Path) -> None:
        """Regression: temp path handed to do_render must keep ``.docx``/``.pptx``."""
        md = tmp_path / "Foo.docx.md"
        md.write_text("# content", encoding="utf-8")
        docx = tmp_path / "Foo.docx"

        captured: list[Path] = []

        def fake_render(md_path: Path, dest: Path) -> None:
            captured.append(dest)
            dest.write_bytes(b"rendered")

        with patch("mdd.sharepoint.apply.actions.do_render", side_effect=fake_render):
            apply_first_sync_md(docx, md)

        assert captured, "do_render was not invoked"
        assert captured[0].suffix == ".docx"


# ---------------------------------------------------------------------------
# SyncRunSummary
# ---------------------------------------------------------------------------


class TestSyncRunSummary:
    def test_has_changes_false_when_all_zero(self) -> None:
        s = SyncRunSummary()
        assert s.has_changes() is False

    def test_has_changes_true_when_first_sync_docx(self) -> None:
        s = SyncRunSummary(first_sync_docx=1)
        assert s.has_changes() is True

    def test_has_changes_true_when_diverged(self) -> None:
        s = SyncRunSummary(diverged=1)
        assert s.has_changes() is True

    def test_no_op_and_word_locked_not_counted_as_changes(self) -> None:
        s = SyncRunSummary(no_op=5, word_locked=2)
        assert s.has_changes() is False


# ---------------------------------------------------------------------------
# _build_commit_message
# ---------------------------------------------------------------------------


class TestBuildCommitMessage:
    def test_includes_site_name(self) -> None:
        s = SyncRunSummary(first_sync_docx=1)
        msg = _build_commit_message(s, "MySharePointSite")
        assert "MySharePointSite" in msg

    def test_includes_counts(self) -> None:
        s = SyncRunSummary(
            first_sync_docx=3,
            first_sync_md=2,
            md_to_docx=4,
            docx_to_md=1,
            diverged=1,
            diverged_paths=["Foo.from-md.docx"],
        )
        msg = _build_commit_message(s, "MySite")
        assert "3 pairs first-synced (docx -> md)" in msg
        assert "2 pairs first-synced (md -> docx)" in msg
        assert "4 pairs: md edited -> docx regenerated" in msg
        assert "docx edited -> md regenerated" in msg
        assert "DIVERGED" in msg
        assert "Foo.from-md.docx" in msg


# ---------------------------------------------------------------------------
# print_dry_run_plan
# ---------------------------------------------------------------------------


class TestPrintDryRunPlan:
    def test_prints_plan_without_writing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        docx = tmp_path / "Report.docx"
        docx.write_bytes(b"x")

        pairs: list[tuple[Path | None, Path | None]] = [(docx, None)]
        print_dry_run_plan(pairs, output_dir=tmp_path)

        out = capsys.readouterr().out
        assert "Report.docx" in out
        assert "first_sync_docx_authoritative" in out
