"""Tests for the pdf-docx subcommand."""

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from mdd.cli import main
from mdd.commands.pdf_docx import DOCX_APPLESCRIPT, export_docx_to_pdf

if TYPE_CHECKING:
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


class TestAppleScriptArguments:
    """The osascript program is a fixed constant; file paths travel as argv."""

    def _run_export(self, tmp_path: Path, name: str) -> tuple[list[str], bool]:
        src = tmp_path / name
        src.write_bytes(b"fake")
        pdf = Path(str(src) + ".pdf")

        def fake_run(argv: list[str], **_: object) -> None:
            pdf.write_bytes(b"%PDF")

        with patch("mdd.utils.pdf_export.subprocess.run", side_effect=fake_run) as mock:
            ok = export_docx_to_pdf(src)

        return list(mock.call_args.args[0]), ok

    def test_script_is_constant_and_paths_are_argv_items(self, tmp_path: Path) -> None:
        argv, ok = self._run_export(tmp_path, "plain.docx")
        src = tmp_path / "plain.docx"

        assert ok is True
        assert argv[:3] == ["osascript", "-e", DOCX_APPLESCRIPT]
        assert argv[3:] == ["--", str(src.resolve()), str(src.resolve()) + ".pdf"]
        assert "on run argv" in argv[2]
        assert 'tell application "Microsoft Word"' in argv[2]
        assert str(tmp_path) not in argv[2]

    def test_quote_and_ampersand_in_name_stay_out_of_script(self, tmp_path: Path) -> None:
        name = 'x" & (do shell script "echo hi") & ".docx'
        argv, ok = self._run_export(tmp_path, name)
        src = tmp_path / name

        assert ok is True
        assert argv[2] == DOCX_APPLESCRIPT
        assert name not in argv[2]
        assert argv[4] == str(src.resolve())
        assert argv[5] == str(src.resolve()) + ".pdf"

    def test_control_character_in_name_is_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "bad\nname.docx").write_bytes(b"fake")
        (tmp_path / "good.docx").write_bytes(b"fake")

        with patch("mdd.commands.pdf_docx.export_docx_to_pdf", return_value=True) as mock:
            result = main(["pdf-docx", str(tmp_path)])

        assert result == 0
        names = [call.args[0].name for call in mock.call_args_list]
        assert names == ["good.docx"]
        assert "control characters" in capsys.readouterr().err
