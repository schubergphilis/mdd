"""Tests for mdd.sharepoint.export — walker and per-file rule dispatcher."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from mdd.sharepoint.export import (
    ExportError,
    ExportSummary,
    _merge_sharepoint_into_frontmatter,  # pyright: ignore[reportPrivateUsage]
    _strip_sharepoint_frontmatter,  # pyright: ignore[reportPrivateUsage]
    _walk_site,  # pyright: ignore[reportPrivateUsage]
    default_output_for_site,
    export_folder,
    export_site,
)
from mdd.sharepoint.models import SharepointCliConfig, SharepointCliSection
from mdd.sharepoint.sync import derive_site_name
from mdd.utils.blacklist import BlacklistError
from tests.mirror_stub import STUB_GROUP, STUB_HOST, stub_backend

if TYPE_CHECKING:
    from pathlib import Path


def _make_sync_root(tmp_path: Path, site_name: str = "Engineering") -> tuple[Path, Path]:
    """Create a fake sync root with a site directory. Returns (sync_root, site_dir)."""
    sync_root = tmp_path / "OneDrive"
    sync_root.mkdir()
    site_dir = sync_root / f"{site_name} - Documents"
    site_dir.mkdir()
    return sync_root, site_dir


class TestDeriveSiteName:
    def test_strips_documents_suffix(self) -> None:
        assert derive_site_name("HR Documentation - Documents") == "HR Documentation"

    def test_no_suffix_returned_unchanged(self) -> None:
        assert derive_site_name("MySite") == "MySite"

    def test_partial_suffix_not_stripped(self) -> None:
        # Only full " - Documents" suffix is stripped
        assert derive_site_name("Meeting Documents") == "Meeting Documents"


class TestExportFolder:
    def test_basic_md_copy(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        (site_dir / "readme.md").write_text("# Hello", encoding="utf-8")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        summary = export_folder(site_dir, output_dir=output_dir)

        out_file = output_dir / "readme.md"
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "sharepoint:" in content
        assert "# Hello" in content
        assert summary.copied == 1
        assert summary.errors == 0

    def test_md_copy_has_frontmatter(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        (site_dir / "notes.md").write_text("Some content", encoding="utf-8")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        export_folder(site_dir, output_dir=output_dir)

        content = (output_dir / "notes.md").read_text(encoding="utf-8")
        assert "---" in content
        assert "sharepoint:" in content
        assert "site:" in content
        assert "MySite" in content
        assert "converter: copy" in content

    def test_md_copy_has_callout(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        (site_dir / "notes.md").write_text("Body text", encoding="utf-8")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        export_folder(site_dir, output_dir=output_dir)

        content = (output_dir / "notes.md").read_text(encoding="utf-8")
        assert "**SharePoint export**" in content

    def test_docx_conversion_called(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        docx_file = site_dir / "report.docx"
        docx_file.write_bytes(b"fake docx content")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        def fake_convert_docx(src: Path, dst: Path) -> None:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text("# Report\n\nConverted content", encoding="utf-8")

        with patch("mdd.sharepoint.export._apply_convert_docx", side_effect=fake_convert_docx):
            summary = export_folder(site_dir, output_dir=output_dir)

        out_file = output_dir / "report.docx.md"
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "sharepoint:" in content
        assert "Converted content" in content
        assert summary.converted == 1

    def test_pptx_conversion_called(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        pptx_file = site_dir / "slides.pptx"
        pptx_file.write_bytes(b"fake pptx")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        def fake_convert_pptx(src: Path, dst: Path) -> None:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text("## Slide 1\n\nContent", encoding="utf-8")

        with patch("mdd.sharepoint.export._apply_convert_pptx", side_effect=fake_convert_pptx):
            summary = export_folder(site_dir, output_dir=output_dir)

        out_file = output_dir / "slides.pptx.md"
        assert out_file.exists()
        assert summary.converted == 1

    def test_xlsx_ignored(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        (site_dir / "data.xlsx").write_bytes(b"fake xlsx")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        summary = export_folder(site_dir, output_dir=output_dir)

        assert not (output_dir / "data.xlsx").exists()
        assert not (output_dir / "data.xlsx.md").exists()
        assert summary.copied == 0
        assert summary.converted == 0

    def test_image_ignored(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        (site_dir / "logo.png").write_bytes(b"\x89PNG")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        summary = export_folder(site_dir, output_dir=output_dir)

        assert not list(output_dir.iterdir())
        assert summary.copied == 0

    def test_unknown_extension_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        (site_dir / "archive.zip").write_bytes(b"PK")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with caplog.at_level(logging.WARNING, logger="mdd"):
            summary = export_folder(site_dir, output_dir=output_dir)

        assert summary.warned == 1
        assert "skip" in caplog.text.lower() or any(
            r.levelno >= logging.WARNING for r in caplog.records
        )

    def test_directory_structure_mirrored(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        subdir = site_dir / "subdir"
        subdir.mkdir(parents=True)
        (subdir / "doc.md").write_text("content", encoding="utf-8")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        export_folder(site_dir, output_dir=output_dir)

        assert (output_dir / "subdir" / "doc.md").exists()

    def test_sibling_md_superseded_docx_not_counted_as_skipped(self, tmp_path: Path) -> None:
        """When docx has a sibling .md, the docx is superseded (not counted as skipped)."""
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        (site_dir / "report.docx").write_bytes(b"fake docx")
        (site_dir / "report.docx.md").write_text("# Already converted", encoding="utf-8")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        mock_converter = MagicMock()
        with patch("mdd.sharepoint.export._apply_convert_docx", mock_converter):
            summary = export_folder(site_dir, output_dir=output_dir)

        # Docx is superseded — should not inflate the skipped counter
        # The sibling .md is copied (1 copied total)
        assert summary.skipped == 0
        assert summary.copied == 1

    def test_sibling_md_means_docx_skipped(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        docx_file = site_dir / "report.docx"
        docx_file.write_bytes(b"fake docx")
        sibling_md = site_dir / "report.docx.md"
        sibling_md.write_text("# Already converted", encoding="utf-8")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        mock_converter = MagicMock()
        with patch("mdd.sharepoint.export._apply_convert_docx", mock_converter):
            export_folder(site_dir, output_dir=output_dir)

        # Converter should NOT be called
        mock_converter.assert_not_called()
        # The sibling .md should be copied
        out_file = output_dir / "report.docx.md"
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "Already converted" in content

    def test_incremental_skip_when_dst_newer(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        src_md = site_dir / "notes.md"
        src_md.write_text("content", encoding="utf-8")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create dst that is "newer" than src
        dst = output_dir / "notes.md"
        dst.write_text("old content", encoding="utf-8")
        # Set dst mtime to be newer
        import os

        src_stat = src_md.stat()
        os.utime(dst, (src_stat.st_mtime + 100, src_stat.st_mtime + 100))

        summary = export_folder(site_dir, output_dir=output_dir)
        assert summary.skipped == 1
        # dst should not be overwritten
        assert dst.read_text(encoding="utf-8") == "old content"

    def test_force_re_exports_up_to_date_file(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        src_md = site_dir / "notes.md"
        src_md.write_text("new content", encoding="utf-8")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        dst = output_dir / "notes.md"
        dst.write_text("old content", encoding="utf-8")
        import os

        src_stat = src_md.stat()
        os.utime(dst, (src_stat.st_mtime + 100, src_stat.st_mtime + 100))

        summary = export_folder(site_dir, output_dir=output_dir, force=True)
        assert summary.skipped == 0
        # dst should be updated (contains new content + frontmatter)
        content = dst.read_text(encoding="utf-8")
        assert "new content" in content

    def test_push_goes_through_the_mirror_backend(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with stub_backend() as backend:
            export_folder(site_dir, output_dir=output_dir, push=True)

        assert backend.pushes == [(output_dir, None)]

    def test_missing_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ExportError, match="does not exist"):
            export_folder(tmp_path / "nonexistent", output_dir=tmp_path / "out")

    def test_file_path_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x")
        with pytest.raises(ExportError, match="not a directory"):
            export_folder(f, output_dir=tmp_path / "out")

    def test_blacklisted_folder_rejected_before_file_write(self, tmp_path: Path) -> None:
        """Blacklist gate must fire before any file is written to output_dir.

        The gate is stubbed rather than driven off the shipped
        data-protection.yaml: which sites are blacklisted is site policy and
        differs per distribution, but the *ordering* guarantee here — refuse
        before walking, before writing — must hold everywhere.
        """
        site_dir = tmp_path / "Confidential"
        site_dir.mkdir()
        (site_dir / "minutes.md").write_text("secret content")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        mock_walk = MagicMock(return_value=[])
        with (
            patch("mdd.sharepoint.export._walk_site", mock_walk),
            patch(
                "mdd.sharepoint.export.check_sharepoint",
                side_effect=BlacklistError("blacklisted"),
            ) as mock_check,
            pytest.raises(BlacklistError),
        ):
            export_folder(site_dir, output_dir=output_dir)

        mock_check.assert_called_once_with("Confidential")
        # Walk should NOT have been called
        mock_walk.assert_not_called()
        # No files written to output_dir
        assert not list(output_dir.iterdir())

    def test_documents_suffix_stripped_for_blacklist_check(self, tmp_path: Path) -> None:
        """' - Documents' suffix is stripped when deriving the site name for the blacklist.

        The OneDrive folder is `Confidential - Documents`, but the blacklist
        is written in terms of site names, so the gate must see
        `Confidential`.
        """
        site_dir = tmp_path / "Confidential - Documents"
        site_dir.mkdir()
        (site_dir / "doc.md").write_text("content")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        mock_walk = MagicMock(return_value=[])
        with (
            patch("mdd.sharepoint.export._walk_site", mock_walk),
            patch(
                "mdd.sharepoint.export.check_sharepoint",
                side_effect=BlacklistError("blacklisted"),
            ) as mock_check,
            pytest.raises(BlacklistError),
        ):
            export_folder(site_dir, output_dir=output_dir)

        mock_check.assert_called_once_with("Confidential")
        mock_walk.assert_not_called()


def _make_config(sync_root: Path) -> SharepointCliConfig:
    """Return a minimal config object pointing at sync_root."""
    return SharepointCliConfig(sharepoint=SharepointCliSection(sync_root=str(sync_root)))


class TestDefaultOutputForSite:
    def test_matching_remote_url_returns_dot(self) -> None:
        import subprocess

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = f"https://{STUB_HOST}/{STUB_GROUP}/Engineering\n"
        with patch("subprocess.run", return_value=mock_result), stub_backend():
            result = default_output_for_site("Engineering", {})
        from pathlib import Path

        assert result == Path()

    def test_non_matching_remote_returns_none(self) -> None:
        import subprocess

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/other/repo\n"
        with patch("subprocess.run", return_value=mock_result), stub_backend():
            result = default_output_for_site("Engineering", {})
        assert result is None

    def test_git_not_found_returns_none(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError), stub_backend():
            result = default_output_for_site("Engineering", {})
        assert result is None

    def test_non_zero_returncode_returns_none(self) -> None:
        import subprocess

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result), stub_backend():
            result = default_output_for_site("Engineering", {})
        assert result is None

    def test_lookalike_domain_returns_none(self) -> None:
        """A URL with the real host as a subdomain of attacker.example must not match."""
        import subprocess

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = f"https://{STUB_HOST}.attacker.example/{STUB_GROUP}/Engineering\n"
        with patch("subprocess.run", return_value=mock_result), stub_backend():
            result = default_output_for_site("Engineering", {})
        assert result is None

    def test_ssh_matching_remote_url_returns_dot(self) -> None:
        """SSH-style remote URL on the correct host should match."""
        import subprocess

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = f"git@{STUB_HOST}:{STUB_GROUP}/Engineering.git\n"
        with patch("subprocess.run", return_value=mock_result), stub_backend():
            result = default_output_for_site("Engineering", {})
        from pathlib import Path

        assert result == Path()


class TestExportSummaryIadd:
    def test_iadd_accumulates_counts(self) -> None:
        a = ExportSummary(copied=1, converted=2, skipped=3, warned=4, errors=5)
        b = ExportSummary(copied=10, converted=20, skipped=30, warned=40, errors=50)
        a += b
        assert a.copied == 11
        assert a.converted == 22
        assert a.skipped == 33
        assert a.warned == 44
        assert a.errors == 55

    def test_iadd_with_zero(self) -> None:
        a = ExportSummary(copied=5)
        a += ExportSummary()
        assert a.copied == 5


class TestStripSharepointFrontmatter:
    def test_strips_sharepoint_frontmatter_block(self) -> None:
        content = "---\nsharepoint:\n  site: X\n---\nBody text\n"
        result = _strip_sharepoint_frontmatter(content)
        assert result == "Body text\n"
        assert "sharepoint:" not in result

    def test_no_frontmatter_returned_unchanged(self) -> None:
        content = "Just body text\n"
        assert _strip_sharepoint_frontmatter(content) == content

    def test_unclosed_frontmatter_returned_unchanged(self) -> None:
        content = "---\nsharepoint:\n  site: X\nno closing fence"
        assert _strip_sharepoint_frontmatter(content) == content

    def test_non_sharepoint_frontmatter_preserved(self) -> None:
        """Quarto/Jekyll frontmatter without sharepoint: key must NOT be stripped."""
        content = "---\ntitle: My Doc\nauthor: Leo\n---\n# Body\n"
        result = _strip_sharepoint_frontmatter(content)
        assert result == content
        assert "title: My Doc" in result

    def test_confluence_frontmatter_preserved(self) -> None:
        content = "---\nconfluence:\n  page_id: 123\n---\n# Body\n"
        result = _strip_sharepoint_frontmatter(content)
        assert result == content


class TestMergeSharepointIntoFrontmatter:
    def test_merges_into_existing_frontmatter(self) -> None:
        body = "---\ntitle: My Doc\nauthor: Leo\n---\n# Body\n"
        result = _merge_sharepoint_into_frontmatter(
            body,
            "MySite",
            "MySite",
            "doc.md",
            "2026-01-01T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
            "copy",
        )
        assert "title: My Doc" in result
        assert "author: Leo" in result
        assert "sharepoint:" in result
        assert "site: MySite" in result
        assert result.startswith("---\n")
        # Should only have one frontmatter block (two --- fences total)
        parts = result.split("---\n")
        assert len(parts) >= 3  # opening, content, closing fence produces 3+ parts

    def test_no_frontmatter_returns_body_unchanged(self) -> None:
        body = "# Just a heading\n\nContent\n"
        result = _merge_sharepoint_into_frontmatter(
            body,
            "MySite",
            "MySite",
            "doc.md",
            "2026-01-01T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
            "copy",
        )
        assert result == body

    def test_preserves_callout(self) -> None:
        body = "---\ntitle: Doc\n---\n# Body\n"
        result = _merge_sharepoint_into_frontmatter(
            body,
            "MySite",
            "MySite",
            "doc.md",
            "2026-01-01T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
            "copy",
        )
        assert "**SharePoint export**" in result


class TestExportFolderConverters:
    def test_pptx_conversion_called(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        (site_dir / "deck.pptx").write_bytes(b"fake pptx")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        def fake_pptx(src: Path, dst: Path) -> None:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text("# Slide\n\ncontent", encoding="utf-8")

        with patch("mdd.sharepoint.export._apply_convert_pptx", side_effect=fake_pptx):
            summary = export_folder(site_dir, output_dir=output_dir)

        assert (output_dir / "deck.pptx.md").exists()
        assert summary.converted == 1

    def test_pdf_conversion_called(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        (site_dir / "report.pdf").write_bytes(b"%PDF-1.4")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        def fake_pdf(src: Path, dst: Path) -> None:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text("# Report\n\ncontent", encoding="utf-8")

        with patch("mdd.sharepoint.export._apply_convert_pdf", side_effect=fake_pdf):
            summary = export_folder(site_dir, output_dir=output_dir)

        assert (output_dir / "report.pdf.md").exists()
        assert summary.converted == 1


class TestFrontmatterMergeInExport:
    def test_quarto_frontmatter_preserved_on_copy(self, tmp_path: Path) -> None:
        """Non-sharepoint frontmatter in a .md file must be preserved, not stripped."""
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        (site_dir / "deck.md").write_text(
            "---\ntitle: My Presentation\nauthor: Leo\n---\n# Slide 1\n",
            encoding="utf-8",
        )
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        export_folder(site_dir, output_dir=output_dir)

        content = (output_dir / "deck.md").read_text(encoding="utf-8")
        assert "title: My Presentation" in content
        assert "author: Leo" in content
        assert "sharepoint:" in content
        # Verify no double frontmatter fences
        lines = content.splitlines()
        fence_count = sum(1 for line in lines if line == "---")
        assert fence_count == 2, f"Expected exactly 2 '---' fences, got {fence_count}"

    def test_sharepoint_frontmatter_replaced_on_re_export(self, tmp_path: Path) -> None:
        """On re-export, existing sharepoint frontmatter is replaced, not duplicated."""
        site_dir = tmp_path / "MySite"
        site_dir.mkdir()
        (site_dir / "notes.md").write_text(
            "---\nsharepoint:\n  site: OldSite\n  repo: old\n  source_path: notes.md\n"
            "  source_mtime: 2025-01-01T00:00:00+00:00\n"
            "  exported_at: 2025-01-01T00:00:00+00:00\n  converter: copy\n---\n# Body\n",
            encoding="utf-8",
        )
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        export_folder(site_dir, output_dir=output_dir, force=True)

        content = (output_dir / "notes.md").read_text(encoding="utf-8")
        assert "site: MySite" in content
        # Should not contain the old site name
        assert "OldSite" not in content
        # Exactly two frontmatter fences
        lines = content.splitlines()
        fence_count = sum(1 for line in lines if line == "---")
        assert fence_count == 2


class TestExportFolderEdgeCases:
    def test_missing_path_raises_export_error(self, tmp_path: Path) -> None:
        with pytest.raises(ExportError, match="does not exist"):
            export_folder(tmp_path / "nonexistent", output_dir=tmp_path / "out")

    def test_file_path_raises_export_error(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x")
        with pytest.raises(ExportError, match="not a directory"):
            export_folder(f, output_dir=tmp_path / "out")

    def test_skip_with_warning_for_unknown_extension(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "Site"
        site_dir.mkdir()
        (site_dir / "archive.zip").write_bytes(b"PK")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = export_folder(site_dir, output_dir=output_dir)

        assert summary.warned == 1
        assert not (output_dir / "archive.zip").exists()

    def test_image_files_ignored(self, tmp_path: Path) -> None:
        site_dir = tmp_path / "Site"
        site_dir.mkdir()
        (site_dir / "photo.png").write_bytes(b"\x89PNG")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = export_folder(site_dir, output_dir=output_dir)

        assert summary.warned == 0
        assert not (output_dir / "photo.png").exists()


class TestExportSite:
    def test_site_not_found_raises_export_error(self, tmp_path: Path) -> None:
        sync_root, _ = _make_sync_root(tmp_path)
        config = _make_config(sync_root)

        with pytest.raises(ExportError, match="not found"):
            export_site(
                "NonExistent",
                config=config,
                mapping={},
                output_dir=tmp_path / "out",
            )

    def test_blacklisted_site_raises_before_file_walk(self, tmp_path: Path) -> None:
        sync_root, site_dir = _make_sync_root(tmp_path, "Confidential")
        (site_dir / "doc.md").write_text("secret content")
        config = _make_config(sync_root)

        mock_walk = MagicMock(return_value=[])
        with (
            patch("mdd.sharepoint.export._walk_site", mock_walk),
            patch(
                "mdd.sharepoint.export.check_sharepoint",
                side_effect=BlacklistError("blacklisted"),
            ),
            pytest.raises(BlacklistError),
        ):
            export_site(
                "Confidential",
                config=config,
                mapping={},
                output_dir=tmp_path / "out",
            )

        # Walk should NOT have been called
        mock_walk.assert_not_called()

    def test_export_site_copies_md(self, tmp_path: Path) -> None:
        sync_root, site_dir = _make_sync_root(tmp_path, "Engineering")
        (site_dir / "notes.md").write_text("# Engineering Notes", encoding="utf-8")
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        config = _make_config(sync_root)

        summary = export_site(
            "Engineering",
            config=config,
            mapping={},
            output_dir=output_dir,
        )

        assert (output_dir / "notes.md").exists()
        assert summary.copied == 1

    def test_export_site_push_goes_through_the_mirror_backend(self, tmp_path: Path) -> None:
        sync_root, _site_dir = _make_sync_root(tmp_path, "Engineering")
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        config = _make_config(sync_root)

        with stub_backend() as backend:
            export_site(
                "Engineering",
                config=config,
                mapping={},
                output_dir=output_dir,
                push=True,
            )

        assert backend.pushes == [(output_dir, None)]


class TestWalkSite:
    def test_returns_regular_files(self, tmp_path: Path) -> None:
        (tmp_path / "doc.md").write_text("content")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "file.docx").write_bytes(b"x")
        result = _walk_site(tmp_path)
        names = {p.name for p in result}
        assert "doc.md" in names
        assert "file.docx" in names

    def test_excludes_dot_files(self, tmp_path: Path) -> None:
        (tmp_path / "doc.md").write_text("content")
        (tmp_path / ".DS_Store").write_bytes(b"x")
        result = _walk_site(tmp_path)
        names = {p.name for p in result}
        assert ".DS_Store" not in names
        assert "doc.md" in names

    def test_excludes_apple_double(self, tmp_path: Path) -> None:
        (tmp_path / "doc.md").write_text("content")
        (tmp_path / "._doc.md").write_bytes(b"x")
        result = _walk_site(tmp_path)
        names = {p.name for p in result}
        assert "._doc.md" not in names

    def test_excludes_files_in_hidden_dirs(self, tmp_path: Path) -> None:
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "file.md").write_text("content")
        (tmp_path / "visible.md").write_text("content")
        result = _walk_site(tmp_path)
        # file.md inside .hidden/ should be excluded
        assert any(p.name == "visible.md" for p in result)
        for p in result:
            assert not any(part.startswith(".") for part in p.relative_to(tmp_path).parts)

    def test_results_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "z.md").write_text("z")
        (tmp_path / "a.md").write_text("a")
        result = _walk_site(tmp_path)
        assert result == sorted(result)
