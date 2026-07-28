"""Tests for the pdf-docx subcommand."""

from typing import TYPE_CHECKING
from unittest.mock import patch

from mdd.cli import main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestPdfDocx:
    def test_nonexistent_directory(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = main(["pdf-docx", "/nonexistent/path"])
        assert result == 1

    def test_no_files_to_export(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        # `-v` raises mdd logging to INFO so progress messages reach stderr.
        result = main(["-v", "pdf-docx", str(tmp_path)])
        assert result == 0
        assert "No DOCX files need exporting" in capsys.readouterr().err

    def test_skips_symlinks(self, tmp_path: Path) -> None:
        docx = tmp_path / "real.docx"
        docx.write_bytes(b"fake")
        link = tmp_path / "link.docx"
        link.symlink_to(docx)

        with patch("mdd.commands.pdf_docx.export_docx_to_pdf", return_value=True) as mock:
            _ = main(["pdf-docx", str(tmp_path)])

        names = [call.args[0].name for call in mock.call_args_list]
        assert "link.docx" not in names
