"""Tests for the pdf-pptx subcommand."""

from typing import TYPE_CHECKING
from unittest.mock import patch

from mdd.cli import main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestPdfPptx:
    def test_nonexistent_directory(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = main(["pdf-pptx", "/nonexistent/path"])
        assert result == 1

    def test_no_files_to_export(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        # `-v` raises mdd logging to INFO so progress messages reach stderr.
        result = main(["-v", "pdf-pptx", str(tmp_path)])
        assert result == 0
        assert "No PPTX files need exporting" in capsys.readouterr().err

    def test_skips_symlinks(self, tmp_path: Path) -> None:
        pptx = tmp_path / "real.pptx"
        pptx.write_bytes(b"fake")
        link = tmp_path / "link.pptx"
        link.symlink_to(pptx)

        with patch("mdd.commands.pdf_pptx.export_pptx_to_pdf", return_value=True) as mock:
            _ = main(["pdf-pptx", str(tmp_path)])

        names = [call.args[0].name for call in mock.call_args_list]
        assert "link.pptx" not in names
