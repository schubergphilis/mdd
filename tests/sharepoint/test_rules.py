"""Tests for mdd.sharepoint.rules — per-file action decision table."""

from __future__ import annotations

from pathlib import Path

from mdd.sharepoint.rules import FileAction, decide
from mdd.utils.mddignore import MddIgnore


class TestDecide:
    def test_docx_no_sibling_returns_convert_docx(self) -> None:
        assert decide(Path("report.docx"), has_sibling_md=False) == FileAction.CONVERT_DOCX

    def test_docx_with_sibling_returns_copy_markdown(self) -> None:
        assert decide(Path("report.docx"), has_sibling_md=True) == FileAction.COPY_MARKDOWN

    def test_doc_no_sibling_returns_convert_docx(self) -> None:
        assert decide(Path("report.doc"), has_sibling_md=False) == FileAction.CONVERT_DOCX

    def test_doc_with_sibling_returns_copy_markdown(self) -> None:
        assert decide(Path("report.doc"), has_sibling_md=True) == FileAction.COPY_MARKDOWN

    def test_pptx_no_sibling_returns_convert_pptx(self) -> None:
        assert decide(Path("slides.pptx"), has_sibling_md=False) == FileAction.CONVERT_PPTX

    def test_pptx_with_sibling_returns_copy_markdown(self) -> None:
        assert decide(Path("slides.pptx"), has_sibling_md=True) == FileAction.COPY_MARKDOWN

    def test_pdf_no_sibling_returns_convert_pdf(self) -> None:
        assert decide(Path("doc.pdf"), has_sibling_md=False) == FileAction.CONVERT_PDF

    def test_pdf_with_sibling_returns_copy_markdown(self) -> None:
        assert decide(Path("doc.pdf"), has_sibling_md=True) == FileAction.COPY_MARKDOWN

    def test_md_returns_copy_markdown(self) -> None:
        assert decide(Path("readme.md"), has_sibling_md=False) == FileAction.COPY_MARKDOWN

    def test_md_with_sibling_flag_still_copy(self) -> None:
        # .md is always COPY_MARKDOWN; sibling flag is irrelevant
        assert decide(Path("readme.md"), has_sibling_md=True) == FileAction.COPY_MARKDOWN

    def test_png_returns_ignore(self) -> None:
        assert decide(Path("image.png"), has_sibling_md=False) == FileAction.IGNORE

    def test_jpg_returns_ignore(self) -> None:
        assert decide(Path("photo.jpg"), has_sibling_md=False) == FileAction.IGNORE

    def test_jpeg_returns_ignore(self) -> None:
        assert decide(Path("photo.jpeg"), has_sibling_md=False) == FileAction.IGNORE

    def test_gif_returns_ignore(self) -> None:
        assert decide(Path("anim.gif"), has_sibling_md=False) == FileAction.IGNORE

    def test_bmp_returns_ignore(self) -> None:
        assert decide(Path("old.bmp"), has_sibling_md=False) == FileAction.IGNORE

    def test_tiff_returns_ignore(self) -> None:
        assert decide(Path("scan.tiff"), has_sibling_md=False) == FileAction.IGNORE

    def test_webp_returns_ignore(self) -> None:
        assert decide(Path("img.webp"), has_sibling_md=False) == FileAction.IGNORE

    def test_svg_returns_ignore(self) -> None:
        assert decide(Path("logo.svg"), has_sibling_md=False) == FileAction.IGNORE

    def test_xlsx_returns_ignore(self) -> None:
        assert decide(Path("data.xlsx"), has_sibling_md=False) == FileAction.IGNORE

    def test_xls_returns_ignore(self) -> None:
        assert decide(Path("old.xls"), has_sibling_md=False) == FileAction.IGNORE

    def test_unknown_extension_returns_skip_with_warning(self) -> None:
        assert decide(Path("archive.zip"), has_sibling_md=False) == FileAction.SKIP_WITH_WARNING

    def test_no_extension_returns_skip_with_warning(self) -> None:
        assert decide(Path("Makefile"), has_sibling_md=False) == FileAction.SKIP_WITH_WARNING

    def test_case_insensitive_docx(self) -> None:
        assert decide(Path("Report.DOCX"), has_sibling_md=False) == FileAction.CONVERT_DOCX

    def test_case_insensitive_pptx(self) -> None:
        assert decide(Path("Slides.PPTX"), has_sibling_md=False) == FileAction.CONVERT_PPTX

    def test_case_insensitive_png(self) -> None:
        assert decide(Path("Image.PNG"), has_sibling_md=False) == FileAction.IGNORE

    def test_path_with_directories(self) -> None:
        assert decide(Path("sub/dir/report.docx"), has_sibling_md=False) == FileAction.CONVERT_DOCX


# ---------------------------------------------------------------------------
# `.mddignore` matcher integration.
# ---------------------------------------------------------------------------


class TestDecideMatcherIntegration:
    def test_matched_path_returns_skip_ignored(self, tmp_path: Path) -> None:
        (tmp_path / ".mddignore").write_text("**/Archive/*\n", encoding="utf-8")
        matcher = MddIgnore.load(tmp_path)
        action = decide(
            Path("Marketing/Archive/old.pptx"),
            has_sibling_md=False,
            matcher=matcher,
            rel_path=Path("Marketing/Archive/old.pptx"),
        )
        assert action is FileAction.SKIP_IGNORED

    def test_unmatched_path_falls_through_to_normal_rules(self, tmp_path: Path) -> None:
        (tmp_path / ".mddignore").write_text("**/Archive/*\n", encoding="utf-8")
        matcher = MddIgnore.load(tmp_path)
        action = decide(
            Path("Marketing/Live/report.docx"),
            has_sibling_md=False,
            matcher=matcher,
            rel_path=Path("Marketing/Live/report.docx"),
        )
        assert action is FileAction.CONVERT_DOCX

    def test_no_matcher_keeps_legacy_behaviour(self) -> None:
        # No matcher → identical behaviour to the two-arg call shape.
        assert (
            decide(Path("report.docx"), has_sibling_md=False, matcher=None, rel_path=None)
            == FileAction.CONVERT_DOCX
        )

    def test_matcher_without_rel_path_is_a_no_op(self, tmp_path: Path) -> None:
        # Defensive: callers that forget to pass *rel_path* must NOT crash;
        # the ignore check is silently skipped.
        (tmp_path / ".mddignore").write_text("*.docx\n", encoding="utf-8")
        matcher = MddIgnore.load(tmp_path)
        action = decide(
            Path("report.docx"),
            has_sibling_md=False,
            matcher=matcher,
            rel_path=None,
        )
        assert action is FileAction.CONVERT_DOCX
