"""PDF picture extraction refuses a symlinked attachments directory and writes real files."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from mdd.convert import pdf as pdf_mod
from mdd.utils.safe_write import SymlinkRefusedError

if TYPE_CHECKING:
    import io
    from pathlib import Path


def _plant_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks not supported on this platform")


def _mock_converter(pictures: list[object]) -> MagicMock:
    doc = MagicMock()
    doc.meta.title = ""
    doc.meta.author = ""
    doc.pages = None
    doc.pictures = pictures
    doc.export_to_markdown.return_value = "body"
    result = MagicMock()
    result.document = doc
    converter = MagicMock()
    converter.convert.return_value = result
    return converter


def _picture(png: bytes) -> MagicMock:
    pic = MagicMock()

    def save(buf: io.BytesIO, format: str) -> None:
        _ = buf.write(png)

    pic.image.pil_image.save.side_effect = save
    return pic


class TestExtractPictures:
    def test_pictures_land_in_real_attachments_dir(self, tmp_path: Path) -> None:
        src = tmp_path / "test.pdf"
        src.write_bytes(b"%PDF-1.4")
        dst = tmp_path / "test.pdf.md"

        with patch.object(
            pdf_mod, "_get_converter", return_value=_mock_converter([_picture(b"PNG1")])
        ):
            pdf_mod.convert_pdf(src, dst, extract_images=True)

        assert (tmp_path / "test.pdf-attachments" / "image1.png").read_bytes() == b"PNG1"

    def test_symlinked_attachments_dir_refused(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        src = tmp_path / "test.pdf"
        src.write_bytes(b"%PDF-1.4")
        dst = tmp_path / "test.pdf.md"
        _plant_symlink(tmp_path / "test.pdf-attachments", outside)

        with (
            patch.object(
                pdf_mod, "_get_converter", return_value=_mock_converter([_picture(b"PNG1")])
            ),
            pytest.raises(SymlinkRefusedError),
        ):
            pdf_mod.convert_pdf(src, dst, extract_images=True)

        assert list(outside.iterdir()) == []
