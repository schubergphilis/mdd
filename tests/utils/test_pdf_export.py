"""PDF export skips and refuses a symlinked ``.pdf`` destination."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from mdd.utils import pdf_export
from mdd.utils.pdf_export import export_to_pdf_via_applescript, find_stale_files

if TYPE_CHECKING:
    from pathlib import Path


def _plant_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks not supported on this platform")


class TestFindStaleFiles:
    def test_missing_pdf_is_stale(self, tmp_path: Path) -> None:
        src = tmp_path / "deck.pptx"
        src.write_bytes(b"x")

        assert find_stale_files(tmp_path, "pptx") == [src]

    def test_newer_pdf_is_not_stale(self, tmp_path: Path) -> None:
        src = tmp_path / "deck.pptx"
        src.write_bytes(b"x")
        pdf = tmp_path / "deck.pptx.pdf"
        pdf.write_bytes(b"pdf")
        mtime = src.stat().st_mtime
        os.utime(pdf, (mtime + 10, mtime + 10))

        assert find_stale_files(tmp_path, "pptx") == []

    def test_symlinked_pdf_is_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "deck.pptx").write_bytes(b"x")
        _plant_symlink(tmp_path / "deck.pptx.pdf", tmp_path / "elsewhere" / "nothere")

        assert find_stale_files(tmp_path, "pptx") == []
        assert "is a symlink" in caplog.text

    def test_symlinked_source_is_skipped(self, tmp_path: Path) -> None:
        real = tmp_path / "real.pptx"
        real.write_bytes(b"x")
        pdf = tmp_path / "real.pptx.pdf"
        pdf.write_bytes(b"pdf")
        mtime = real.stat().st_mtime
        os.utime(pdf, (mtime + 10, mtime + 10))
        _plant_symlink(tmp_path / "link.pptx", real)

        assert find_stale_files(tmp_path, "pptx") == []


class TestExportToPdf:
    def test_symlinked_pdf_is_refused_before_office_runs(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        src = tmp_path / "deck.pptx"
        src.write_bytes(b"x")
        _plant_symlink(tmp_path / "deck.pptx.pdf", outside / "target.pdf")

        with patch.object(pdf_export.subprocess, "run") as run:
            ok = export_to_pdf_via_applescript(src, "script", "PowerPoint")

        assert ok is False
        run.assert_not_called()
        assert list(outside.iterdir()) == []

    def test_pdf_path_is_not_resolved_through_a_link(self, tmp_path: Path) -> None:
        src = tmp_path / "deck.pptx"
        src.write_bytes(b"x")
        pdf = tmp_path / "deck.pptx.pdf"

        def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
            assert cmd[-1] == str(tmp_path.resolve() / "deck.pptx.pdf")
            pdf.write_bytes(b"pdf")
            return MagicMock()

        with patch.object(pdf_export.subprocess, "run", side_effect=fake_run):
            ok = export_to_pdf_via_applescript(src, "script", "PowerPoint")

        assert ok is True

    def test_link_created_by_office_counts_as_failure(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "target.pdf").write_bytes(b"pdf")
        src = tmp_path / "deck.pptx"
        src.write_bytes(b"x")

        def fake_run(_cmd: list[str], **_kw: object) -> MagicMock:
            (tmp_path / "deck.pptx.pdf").symlink_to(outside / "target.pdf")
            return MagicMock()

        with patch.object(pdf_export.subprocess, "run", side_effect=fake_run):
            ok = export_to_pdf_via_applescript(src, "script", "PowerPoint")

        assert ok is False

    def test_applescript_failure_is_reported(self, tmp_path: Path) -> None:
        src = tmp_path / "deck.pptx"
        src.write_bytes(b"x")
        error = subprocess.CalledProcessError(1, ["osascript"], stderr="boom")

        with patch.object(pdf_export.subprocess, "run", side_effect=error):
            ok = export_to_pdf_via_applescript(src, "script", "PowerPoint")

        assert ok is False
