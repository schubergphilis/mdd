"""Tests for the unified pdf subcommand."""

from typing import TYPE_CHECKING
from unittest.mock import patch

from mdd.cli import main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestPdf:
    def test_empty_directory_succeeds(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # `-v` raises mdd logging to INFO so progress messages reach stderr.
        result = main(["-v", "pdf", str(tmp_path)])
        assert result == 0
        err = capsys.readouterr().err
        assert "PPTX" in err
        assert "DOCX" in err

    def test_returns_one_on_failure(self, tmp_path: Path) -> None:
        pptx = tmp_path / "test.pptx"
        pptx.write_bytes(b"fake")

        with patch("mdd.commands.pdf_pptx.export_pptx_to_pdf", return_value=False):
            result = main(["pdf", str(tmp_path)])
        assert result == 1

    def test_pptx_failure_reported_to_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """#53: per-pipeline failures must be reported to stderr."""
        pptx = tmp_path / "test.pptx"
        pptx.write_bytes(b"fake")

        with patch("mdd.commands.pdf_pptx.export_pptx_to_pdf", return_value=False):
            _ = main(["pdf", str(tmp_path)])

        err = capsys.readouterr().err
        assert "PPTX" in err

    def test_docx_failure_reported_to_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """#53: per-pipeline failures must be reported to stderr."""
        docx = tmp_path / "test.docx"
        docx.write_bytes(b"fake")

        with patch("mdd.commands.pdf_docx.export_docx_to_pdf", return_value=False):
            _ = main(["pdf", str(tmp_path)])

        err = capsys.readouterr().err
        assert "DOCX" in err
