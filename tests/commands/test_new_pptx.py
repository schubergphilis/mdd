"""Tests for the new-pptx subcommand."""

from typing import TYPE_CHECKING

import pytest

from mdd.cli import main

if TYPE_CHECKING:
    from pathlib import Path


class TestNewPptx:
    def test_no_args_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _ = main(["new-pptx"])
        assert exc_info.value.code == 2

    def test_creates_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = main(["new-pptx", "my-talk"])
        assert result == 0
        assert (tmp_path / "my-talk" / "my-talk.qmd").exists()
        assert (tmp_path / "my-talk" / "render.sh").exists()

    def test_qmd_contains_title(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _ = main(["new-pptx", "my-talk"])
        content = (tmp_path / "my-talk" / "my-talk.qmd").read_text()
        assert "my-talk" in content
