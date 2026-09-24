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


def _plant_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks not supported on this platform")


class TestNewRefusesSymlinks:
    def test_render_sh_symlink_leaves_victim_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        victim = tmp_path / "victim.sh"
        victim.write_text("original", encoding="utf-8")
        project = tmp_path / "my-project"
        project.mkdir()
        _plant_symlink(project / "render.sh", victim)
        monkeypatch.chdir(tmp_path)

        result = main(["new", "my-project"])

        assert result == 1
        assert victim.read_text(encoding="utf-8") == "original"
        assert (victim.stat().st_mode & 0o111) == 0
        assert (project / "render.sh").is_symlink()

    def test_dangling_qmd_symlink_target_not_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        project = tmp_path / "my-project"
        project.mkdir()
        _plant_symlink(project / "my-project.qmd", outside / "target")
        monkeypatch.chdir(tmp_path)

        result = main(["new", "my-project"])

        assert result == 1
        assert not (outside / "target").exists()
        assert not (project / "render.sh").exists()

    def test_existing_render_sh_is_not_overwritten(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "my-project"
        project.mkdir()
        (project / "render.sh").write_text("mine", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = main(["new", "my-project"])

        assert result == 1
        assert (project / "render.sh").read_text(encoding="utf-8") == "mine"
