"""Tests for the pdf-docx subcommand."""

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from mdd.cli import main
from mdd.commands.pdf_docx import build_docx_applescript, export_docx_to_pdf

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

    def _run_export(
        self, tmp_path: Path, name: str, *, update_fields: bool = True
    ) -> tuple[list[str], bool]:
        src = tmp_path / name
        src.write_bytes(b"fake")
        pdf = Path(str(src) + ".pdf")

        def fake_run(argv: list[str], **_: object) -> None:
            pdf.write_bytes(b"%PDF")

        with patch("mdd.utils.pdf_export.subprocess.run", side_effect=fake_run) as mock:
            ok = export_docx_to_pdf(src, update_fields=update_fields)

        return list(mock.call_args.args[0]), ok

    def test_script_is_constant_and_paths_are_argv_items(self, tmp_path: Path) -> None:
        argv, ok = self._run_export(tmp_path, "plain.docx")
        src = tmp_path / "plain.docx"

        assert ok is True
        assert argv[:3] == ["osascript", "-e", build_docx_applescript(update_fields=True)]
        assert argv[3:] == ["--", str(src.resolve()), str(src.resolve()) + ".pdf"]
        assert "on run argv" in argv[2]
        assert 'tell application "Microsoft Word"' in argv[2]
        assert str(tmp_path) not in argv[2]

    def test_quote_and_ampersand_in_name_stay_out_of_script(self, tmp_path: Path) -> None:
        name = 'x" & (do shell script "echo hi") & ".docx'
        argv, ok = self._run_export(tmp_path, name)
        src = tmp_path / name

        assert ok is True
        assert argv[2] == build_docx_applescript(update_fields=True)
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

    def test_no_update_fields_script_is_passed_through(self, tmp_path: Path) -> None:
        argv, ok = self._run_export(tmp_path, "plain.docx", update_fields=False)

        assert ok is True
        assert argv[2] == build_docx_applescript(update_fields=False)


class TestDocxAppleScript:
    """Pin the steps that keep the PDF correct, so a simplification cannot drop them."""

    def test_default_updates_tables_of_contents_before_export(self) -> None:
        script = build_docx_applescript(update_fields=True)

        toc_update = script.index("repeat with theToc in (get tables of contents of theDoc)")
        assert "update theToc" in script
        assert toc_update < script.index("save as theDoc")

    def test_general_field_pass_is_best_effort(self) -> None:
        script = build_docx_applescript(update_fields=True)

        field_loop = script.index("repeat with theField in (get fields of theDoc)")
        assert "update field theField" in script
        # The field loop sits inside a `try` so a failure to enumerate
        # fields does not abort the export.
        assert script.rindex("try", 0, field_loop) > script.index("update theToc")

    def test_toc_pass_does_not_iterate_fields(self) -> None:
        script = build_docx_applescript(update_fields=True)

        assert script.index("tables of contents") < script.index("fields of theDoc")

    def test_open_copy_is_closed_unsaved_before_open(self) -> None:
        for update_fields in (True, False):
            script = build_docx_applescript(update_fields=update_fields)

            pre_close = script.index("repeat with i from (count of documents) to 1 by -1")
            assert "close document i saving no" in script
            assert "docName is srcPath or docName is srcHfsPath" in script
            assert pre_close < script.index("open srcFile")

    def test_source_is_never_saved(self) -> None:
        script = build_docx_applescript(update_fields=True)

        assert "close theDoc saving no" in script
        assert "saving yes" not in script

    def test_no_update_fields_omits_update_steps(self) -> None:
        script = build_docx_applescript(update_fields=False)

        assert "tables of contents" not in script
        assert "fields of theDoc" not in script
        assert "update" not in script
        assert "save as theDoc file name pdfFile file format format PDF" in script


class TestNoUpdateFieldsFlag:
    def _exported_update_fields(self, tmp_path: Path, extra: list[str]) -> list[bool]:
        (tmp_path / "doc.docx").write_bytes(b"fake")

        with patch("mdd.commands.pdf_docx.export_docx_to_pdf", return_value=True) as mock:
            result = main(["pdf-docx", *extra, str(tmp_path)])

        assert result == 0
        return [bool(call.kwargs["update_fields"]) for call in mock.call_args_list]

    def test_fields_are_updated_by_default(self, tmp_path: Path) -> None:
        assert self._exported_update_fields(tmp_path, []) == [True]

    def test_flag_disables_field_update(self, tmp_path: Path) -> None:
        assert self._exported_update_fields(tmp_path, ["--no-update-fields"]) == [False]

    def test_pdf_command_updates_fields(self, tmp_path: Path) -> None:
        (tmp_path / "doc.docx").write_bytes(b"fake")

        with patch("mdd.commands.pdf_docx.export_docx_to_pdf", return_value=True) as mock:
            result = main(["pdf", str(tmp_path)])

        assert result == 0
        assert [call.kwargs["update_fields"] for call in mock.call_args_list] == [True]
