"""Tests for mdd.convert.pdf — convert_pdf function.

PDF conversion relies on Docling (ML models), so all tests here are marked
integration. They require network access on first run to download models.
Unit tests for error-handling paths use mocks.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_doc(
    *,
    title: str = "",
    author: str = "",
    pages: object = None,
    markdown: str = "",
    pictures: list[object] | None = None,
) -> MagicMock:
    """Build a mock Docling document for unit tests."""
    doc = MagicMock()
    meta = MagicMock()
    meta.title = title
    meta.author = author
    doc.meta = meta
    doc.pages = pages
    doc.pictures = pictures or []
    doc.export_to_markdown.return_value = markdown
    return doc


def _make_mock_converter(doc: MagicMock) -> MagicMock:
    result = MagicMock()
    result.document = doc
    converter = MagicMock()
    converter.convert.return_value = result
    return converter


class TestPdfImageExtractionWarning:
    """#35: failed image extraction must emit a warning, not silently swallow errors."""

    def test_warning_emitted_on_image_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from mdd.convert import pdf as pdf_mod

        broken_pic = MagicMock()
        broken_pic.image.pil_image.save.side_effect = RuntimeError("corrupt image data")
        doc = _make_mock_doc(pictures=[broken_pic])
        converter = _make_mock_converter(doc)

        # mdd.utils.logging.configure() may have set propagate=False on the
        # ``mdd`` root logger in a previous test; attach caplog directly so
        # we capture records regardless of propagation state.
        mdd_log = logging.getLogger("mdd.convert.pdf")
        mdd_log.addHandler(caplog.handler)
        try:
            with (
                patch.object(pdf_mod, "_get_converter", return_value=converter),
                caplog.at_level(logging.WARNING, logger="mdd.convert.pdf"),
            ):
                src = tmp_path / "test.pdf"
                src.write_bytes(b"%PDF-1.4")
                dst = tmp_path / "test.pdf.md"
                pdf_mod.convert_pdf(src, dst, extract_images=True)
        finally:
            mdd_log.removeHandler(caplog.handler)

        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "image" in msgs.lower()
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_summary_count_on_multiple_failures(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from mdd.convert import pdf as pdf_mod

        broken = MagicMock()
        broken.image.pil_image.save.side_effect = RuntimeError("bad")
        doc = _make_mock_doc(pictures=[broken, broken])
        converter = _make_mock_converter(doc)

        mdd_log = logging.getLogger("mdd.convert.pdf")
        mdd_log.addHandler(caplog.handler)
        try:
            with (
                patch.object(pdf_mod, "_get_converter", return_value=converter),
                caplog.at_level(logging.WARNING, logger="mdd.convert.pdf"),
            ):
                src = tmp_path / "test.pdf"
                src.write_bytes(b"%PDF-1.4")
                dst = tmp_path / "test.pdf.md"
                pdf_mod.convert_pdf(src, dst, extract_images=True)
        finally:
            mdd_log.removeHandler(caplog.handler)

        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "2" in msgs


class TestPdfPageCountErrorHandling:
    """#59: page count errors should catch both TypeError and AttributeError."""

    def test_attribute_error_in_len_gives_zero(self, tmp_path: Path) -> None:
        from mdd.convert import pdf as pdf_mod

        pages = MagicMock()
        pages.__len__ = MagicMock(side_effect=AttributeError("no __len__"))
        doc = _make_mock_doc(pages=pages)
        converter = _make_mock_converter(doc)

        with patch.object(pdf_mod, "_get_converter", return_value=converter):
            src = tmp_path / "test.pdf"
            src.write_bytes(b"%PDF-1.4")
            dst = tmp_path / "test.pdf.md"
            pdf_mod.convert_pdf(src, dst)  # must not raise

        content = dst.read_text()
        assert "source_path:" in content

    def test_type_error_in_len_gives_zero(self, tmp_path: Path) -> None:
        from mdd.convert import pdf as pdf_mod

        pages = MagicMock()
        pages.__len__ = MagicMock(side_effect=TypeError("not sized"))
        doc = _make_mock_doc(pages=pages)
        converter = _make_mock_converter(doc)

        with patch.object(pdf_mod, "_get_converter", return_value=converter):
            src = tmp_path / "test.pdf"
            src.write_bytes(b"%PDF-1.4")
            dst = tmp_path / "test.pdf.md"
            pdf_mod.convert_pdf(src, dst)

        content = dst.read_text()
        assert "source_path:" in content


class TestPdfSourcePathDeterministic:
    """#65: source_path must be an absolute path, not cwd-relative."""

    def test_source_path_is_absolute(self, tmp_path: Path) -> None:
        from mdd.convert import pdf as pdf_mod

        doc = _make_mock_doc()
        converter = _make_mock_converter(doc)

        with patch.object(pdf_mod, "_get_converter", return_value=converter):
            src = tmp_path / "subdir" / "test.pdf"
            src.parent.mkdir()
            src.write_bytes(b"%PDF-1.4")
            dst = tmp_path / "test.pdf.md"
            pdf_mod.convert_pdf(src, dst)

        import yaml

        content = dst.read_text()
        lines = content.splitlines()
        fm_end = lines.index("---", 1)
        fm_text = "\n".join(lines[1:fm_end])
        data = yaml.safe_load(fm_text)
        recorded = data["pdf"]["source_path"]
        assert Path(recorded).is_absolute(), f"Expected absolute path, got: {recorded!r}"


class TestPdfConverterSingleton:
    """#27: _get_converter() must return the same instance across calls."""

    def test_singleton_across_calls(self) -> None:
        import docling.document_converter as dc_mod

        import mdd.convert.pdf as pdf_mod

        original_ctor = dc_mod.DocumentConverter
        pdf_mod._get_converter.cache_clear()  # pyright: ignore[reportPrivateUsage]
        try:
            mock_instance = MagicMock()
            dc_mod.DocumentConverter = MagicMock(return_value=mock_instance)  # type: ignore[attr-defined]
            c1 = pdf_mod._get_converter()  # pyright: ignore[reportPrivateUsage]
            # Singleton: a second call must reuse the cached instance, even
            # if the underlying DocumentConverter factory would yield a new one.
            dc_mod.DocumentConverter = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
            c2 = pdf_mod._get_converter()  # pyright: ignore[reportPrivateUsage]
            assert c1 is mock_instance
            assert c2 is c1
        finally:
            pdf_mod._get_converter.cache_clear()  # pyright: ignore[reportPrivateUsage]
            dc_mod.DocumentConverter = original_ctor  # type: ignore[attr-defined]

    def test_multiple_convert_pdf_calls_reuse_converter(self, tmp_path: Path) -> None:
        """#27: multiple convert_pdf() calls must not create multiple converters."""
        from mdd.convert import pdf as pdf_mod

        pdf_mod._get_converter.cache_clear()  # pyright: ignore[reportPrivateUsage]
        try:
            doc = _make_mock_doc()
            converter = _make_mock_converter(doc)

            with patch.object(pdf_mod, "_get_converter", return_value=converter) as mock_get:
                for i in range(3):
                    src = tmp_path / f"test{i}.pdf"
                    src.write_bytes(b"%PDF-1.4")
                    dst = tmp_path / f"test{i}.pdf.md"
                    pdf_mod.convert_pdf(src, dst)

            # _get_converter must be called once per convert_pdf call but the
            # underlying factory is only called once (singleton guarantee is in _get_converter
            # itself; this test checks convert_pdf delegates to it)
            assert mock_get.call_count == 3
        finally:
            pdf_mod._get_converter.cache_clear()  # pyright: ignore[reportPrivateUsage]


class TestPdfFrontmatterYamlEncoding:
    """#24: PDF frontmatter must use proper YAML encoding."""

    def test_title_with_apostrophe_parses_correctly(self, tmp_path: Path) -> None:
        from mdd.convert import pdf as pdf_mod

        doc = _make_mock_doc(title="O'Reilly")
        converter = _make_mock_converter(doc)

        with patch.object(pdf_mod, "_get_converter", return_value=converter):
            src = tmp_path / "test.pdf"
            src.write_bytes(b"%PDF-1.4")
            dst = tmp_path / "test.pdf.md"
            pdf_mod.convert_pdf(src, dst)

        import yaml

        content = dst.read_text()
        lines = content.splitlines()
        fm_end = lines.index("---", 1)
        fm_text = "\n".join(lines[1:fm_end])
        data = yaml.safe_load(fm_text)
        assert data["pdf"]["title"] == "O'Reilly"


@pytest.mark.integration
class TestConvertPdf:
    def test_produces_md_file(self, tmp_path: Path) -> None:
        """convert_pdf produces a .pdf.md file without crashing."""
        from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

        from mdd.convert.pdf import convert_pdf

        src = tmp_path / "sample.pdf"
        dst = tmp_path / "sample.pdf.md"
        c = canvas.Canvas(str(src))
        c.drawString(100, 750, "Hello, World!")
        c.showPage()
        c.save()

        convert_pdf(src, dst)
        assert dst.exists()
        content = dst.read_text()
        assert content.strip()

    def test_frontmatter_present(self, tmp_path: Path) -> None:
        """convert_pdf includes pdf: frontmatter block."""
        from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

        from mdd.convert.pdf import convert_pdf

        src = tmp_path / "sample.pdf"
        dst = tmp_path / "sample.pdf.md"
        c = canvas.Canvas(str(src))
        c.drawString(100, 750, "Test content")
        c.showPage()
        c.save()

        convert_pdf(src, dst)
        content = dst.read_text()
        assert "pdf:" in content
        assert "source_path:" in content
