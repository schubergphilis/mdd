"""Tests for path-based file discovery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mdd.prose.walk import discover, missing

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def build(root: Path) -> None:
    _ = (root / "a.md").write_text("a\n", encoding="utf-8")
    _ = (root / "b.qmd").write_text("b\n", encoding="utf-8")
    _ = (root / "c.txt").write_text("c\n", encoding="utf-8")
    (root / "sub").mkdir()
    _ = (root / "sub" / "d.md").write_text("d\n", encoding="utf-8")
    (root / ".git").mkdir()
    _ = (root / ".git" / "e.md").write_text("e\n", encoding="utf-8")


def names(paths: list[Path], root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in paths)


def test_directory_walk_finds_md_and_qmd(tmp_path: Path) -> None:
    build(tmp_path)
    assert names(discover([tmp_path]), tmp_path) == ["a.md", "b.qmd", "sub/d.md"]


def test_git_directory_is_skipped(tmp_path: Path) -> None:
    build(tmp_path)
    assert not any(".git" in str(p) for p in discover([tmp_path]))


def test_mddignore_is_honoured(tmp_path: Path) -> None:
    build(tmp_path)
    _ = (tmp_path / ".mddignore").write_text("sub/\n", encoding="utf-8")
    assert names(discover([tmp_path]), tmp_path) == ["a.md", "b.qmd"]


def test_extra_ignore_files_are_unioned(tmp_path: Path) -> None:
    build(tmp_path)
    extra = tmp_path / "extra-ignore"
    _ = extra.write_text("*.qmd\n", encoding="utf-8")
    found = discover([tmp_path], extra_ignores=(extra,))
    assert names(found, tmp_path) == ["a.md", "sub/d.md"]


def test_a_named_file_is_taken_as_given(tmp_path: Path) -> None:
    build(tmp_path)
    _ = (tmp_path / ".mddignore").write_text("a.md\n", encoding="utf-8")
    assert discover([tmp_path / "a.md"]) == [tmp_path / "a.md"]


def test_duplicates_are_collapsed(tmp_path: Path) -> None:
    build(tmp_path)
    found = discover([tmp_path, tmp_path / "a.md"])
    assert len([p for p in found if p.name == "a.md"]) == 1


def test_absent_paths_are_skipped_and_reported(tmp_path: Path) -> None:
    assert discover([tmp_path / "nope"]) == []
    assert missing([tmp_path / "nope"]) == [tmp_path / "nope"]
    assert missing([tmp_path]) == []


def test_default_target_is_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert sorted(str(p) for p in discover([])) == ["a.md", "b.qmd", "sub/d.md"]
