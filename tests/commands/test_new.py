"""Tests for the new subcommand (combined PPTX + DOCX project)."""

from typing import TYPE_CHECKING

import pytest

from mdd.cli import main

if TYPE_CHECKING:
    from pathlib import Path


class TestNew:
    def test_no_args_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _ = main(["new"])
        assert exc_info.value.code == 2

    def test_creates_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = main(["new", "my-project"])
        assert result == 0
        assert (tmp_path / "my-project" / "my-project.qmd").exists()
