"""``mdd convert`` skips symlinked sources and refuses symlinked output directories."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from mdd.cli import main as cli_main
from mdd.commands.convert import collect_files
from mdd.convert import pdf as pdf_mod
from mdd.convert.images import write_image
from mdd.converters.docx import DocxConverter
from mdd.converters.pptx import PptxConverter
from mdd.utils.safe_write import SymlinkRefusedError

if TYPE_CHECKING:
    from pathlib import Path


def _plant_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks not supported on this platform")


def _make_pptx(path: Path) -> Path:
    import pptx  # pyright: ignore[reportMissingModuleSource]

    prs: Any = pptx.Presentation()  # pyright: ignore[reportAny]
    slide: Any = prs.slides.add_slide(prs.slide_layouts[0])  # pyright: ignore[reportAny]
    slide.shapes.title.text = "Test Slide"
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))
    return path


def _make_docx(path: Path) -> Path:
    from docx import Document  # pyright: ignore[reportMissingModuleSource]

    doc: Any = Document()  # pyright: ignore[reportAny]
    doc.add_paragraph("Hello")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


class TestCollectFiles:
    def test_symlinked_file_in_walk_is_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        outside = _make_pptx(tmp_path / "outside" / "secret.pptx")
        src = tmp_path / "src"
        real = _make_pptx(src / "real.pptx")
        _plant_symlink(src / "leak.pptx", outside)

        assert collect_files(src) == [real]
        assert "skipping symlink" in caplog.text

    def test_dangling_symlink_in_walk_is_skipped(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        _plant_symlink(src / "gone.docx", tmp_path / "nothere.docx")

        assert collect_files(src) == []

    def test_named_symlinked_file_is_followed_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        real = _make_pptx(tmp_path / "real.pptx")
        link = tmp_path / "link.pptx"
        _plant_symlink(link, real)

        assert collect_files(link) == [link]
        assert "following symlink" in caplog.text

    def test_file_flag_symlink_is_followed_with_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        real = _make_pptx(tmp_path / "real.pptx")
        link = tmp_path / "link.pptx"
        _plant_symlink(link, real)

        assert cli_main(["convert", "--file", str(link)]) == 0
        assert (tmp_path / "link.pptx.md").is_file()
        assert "following symlink" in capsys.readouterr().err


class TestDestDir:
    def test_symlinked_subdir_below_dest_dir_is_refused(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        _make_pptx(src / "sub" / "deck.pptx")
        dest = tmp_path / "dest"
        dest.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        _plant_symlink(dest / "sub", outside)

        assert cli_main(["convert", "--dest-dir", str(dest), str(src)]) == 1
        assert list(outside.iterdir()) == []

    def test_symlinked_dest_dir_itself_is_accepted(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        _make_pptx(src / "sub" / "deck.pptx")
        _make_pptx(src / "top.pptx")
        real = tmp_path / "real"
        real.mkdir()
        dest = tmp_path / "dest"
        _plant_symlink(dest, real)

        assert cli_main(["convert", "--dest-dir", str(dest), str(src)]) == 0
        assert (real / "sub" / "deck.pptx.md").is_file()
        assert (real / "top.pptx.md").is_file()

    def test_in_place_output_is_written(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        _make_pptx(src / "sub" / "deck.pptx")

        assert cli_main(["convert", str(src)]) == 0
        assert (src / "sub" / "deck.pptx.md").is_file()


class TestConvertersHonourRoot:
    def test_pptx_refuses_symlinked_parent(self, tmp_path: Path) -> None:
        src = _make_pptx(tmp_path / "deck.pptx")
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        _plant_symlink(root / "sub", outside)

        with pytest.raises(SymlinkRefusedError):
            _ = PptxConverter().convert(src, dest=root / "sub" / "deck.pptx.md", root=root)

        assert list(outside.iterdir()) == []

    def test_docx_refuses_symlinked_parent(self, tmp_path: Path) -> None:
        src = _make_docx(tmp_path / "doc.docx")
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        _plant_symlink(root / "sub", outside)

        with (
            patch("mdd.converters.docx.convert_body", return_value="Hello"),
            pytest.raises(SymlinkRefusedError),
        ):
            _ = DocxConverter().convert(src, dest=root / "sub" / "doc.docx.md", root=root)

        assert list(outside.iterdir()) == []

    def test_pdf_refuses_symlinked_parent(self, tmp_path: Path) -> None:
        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF-1.4")
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        _plant_symlink(root / "sub", outside)
        doc = MagicMock()
        doc.meta.title = ""
        doc.meta.author = ""
        doc.pages = None
        doc.pictures = []
        doc.export_to_markdown.return_value = "body"
        converter = MagicMock()
        converter.convert.return_value.document = doc

        with (
            patch.object(pdf_mod, "_get_converter", return_value=converter),
            pytest.raises(SymlinkRefusedError),
        ):
            pdf_mod.convert_pdf(src, root / "sub" / "doc.pdf.md", root=root)

        assert list(outside.iterdir()) == []

    def test_image_write_refuses_symlinked_dir_below_root(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        _plant_symlink(root / "sub", outside)

        with pytest.raises(SymlinkRefusedError):
            _ = write_image(
                root / "sub" / "deck-attachments",
                _png(),
                "png",
                cache={},
                on_drop=lambda _r: None,
                root=root,
            )

        assert list(outside.iterdir()) == []

    def test_image_write_below_real_root_succeeds(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        result = write_image(
            root / "sub" / "deck-attachments",
            _png(),
            "png",
            cache={},
            on_drop=lambda _r: None,
            root=tmp_path,
        )

        assert result is not None
        assert (root / "sub" / "deck-attachments" / result.rel_path).is_file()
