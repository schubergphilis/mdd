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

    def test_default_references_default_template(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert main(["new-pptx", "my-talk"]) == 0
        content = (tmp_path / "my-talk" / "my-talk.qmd").read_text()
        assert "reference-doc: simple-presentation.pptx" in content
        assert "compact" not in content
        link = tmp_path / "my-talk" / "simple-presentation.pptx"
        assert link.is_symlink()
        assert link.resolve().is_file()
        assert not (tmp_path / "my-talk" / "simple-presentation-compact.pptx").exists()


class TestNewPptxCompact:
    def test_creates_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert main(["new-pptx", "--compact", "dense-talk"]) == 0
        assert (tmp_path / "dense-talk" / "dense-talk.qmd").exists()
        assert (tmp_path / "dense-talk" / "render.sh").exists()

    def test_qmd_references_compact_template(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert main(["new-pptx", "dense-talk", "--compact"]) == 0
        content = (tmp_path / "dense-talk" / "dense-talk.qmd").read_text()
        assert "reference-doc: simple-presentation-compact.pptx" in content
        assert "dense-talk" in content

    def test_symlinks_compact_template_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert main(["new-pptx", "dense-talk", "--compact"]) == 0
        link = tmp_path / "dense-talk" / "simple-presentation-compact.pptx"
        assert link.is_symlink()
        assert link.resolve().is_file()
        assert not (tmp_path / "dense-talk" / "simple-presentation.pptx").exists()
