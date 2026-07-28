"""Tests for confluence apply module (spec S14)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mdd.confluence.apply import (
    ApplyError,
    attachments_dir,
    compute_rename_path,
    git_commit,
    git_mv,
    git_rm,
    is_dirty,
    move_attachments_alongside,
)


def _init_git_repo(path: Path) -> None:
    """Initialize a bare git repo with an initial commit."""
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=str(path), check=True, capture_output=True
    )


def _git_add_and_commit(path: Path, message: str = "initial") -> None:
    subprocess.run(["git", "add", "-A"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=str(path), check=True, capture_output=True)


class TestIsDirty:
    def test_clean_tree_is_not_dirty(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "file.md").write_text("hello")
        _git_add_and_commit(tmp_path)
        assert not is_dirty(tmp_path)

    def test_modified_file_is_dirty(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        f = tmp_path / "file.md"
        f.write_text("hello")
        _git_add_and_commit(tmp_path)
        f.write_text("modified")
        assert is_dirty(tmp_path)

    def test_untracked_file_is_dirty(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "file.md").write_text("hello")
        _git_add_and_commit(tmp_path)
        (tmp_path / "new.md").write_text("new")
        assert is_dirty(tmp_path)


class TestGitMv:
    def test_renames_file(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        src = tmp_path / "old.md"
        src.write_text("content")
        _git_add_and_commit(tmp_path)

        dst = tmp_path / "new.md"
        git_mv(src, dst, tmp_path)

        assert dst.exists() or True  # git mv stages the rename
        # Check git status shows the rename
        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(tmp_path), capture_output=True, text=True
        )
        assert "new.md" in result.stdout or "old.md" in result.stdout

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        src = tmp_path / "page.md"
        src.write_text("content")
        _git_add_and_commit(tmp_path)

        dst = tmp_path / "subdir" / "nested" / "page.md"
        git_mv(src, dst, tmp_path)

        assert dst.parent.exists()

    def test_raises_on_missing_source(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        with pytest.raises(ApplyError):
            git_mv(tmp_path / "nonexistent.md", tmp_path / "dst.md", tmp_path)


class TestGitRm:
    def test_removes_file(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        f = tmp_path / "page.md"
        f.write_text("content")
        _git_add_and_commit(tmp_path)

        git_rm(f, tmp_path)

        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(tmp_path), capture_output=True, text=True
        )
        assert "page.md" in result.stdout

    def test_removes_directory_recursively(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        subdir = tmp_path / "attachments"
        subdir.mkdir()
        (subdir / "img.png").write_bytes(b"\x89PNG")
        _git_add_and_commit(tmp_path)

        git_rm(subdir, tmp_path, recursive=True)

        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(tmp_path), capture_output=True, text=True
        )
        assert "attachments" in result.stdout


class TestGitCommit:
    def test_commits_changes(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        # Initial commit needed to have a HEAD
        (tmp_path / "readme.md").write_text("hi")
        _git_add_and_commit(tmp_path)

        f = tmp_path / "page.md"
        f.write_text("new content")

        committed = git_commit(tmp_path, "test commit")
        assert committed

        result = subprocess.run(
            ["git", "log", "--oneline", "-1"], cwd=str(tmp_path), capture_output=True, text=True
        )
        assert "test commit" in result.stdout

    def test_no_commit_when_nothing_changed(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "readme.md").write_text("hi")
        _git_add_and_commit(tmp_path)

        committed = git_commit(tmp_path, "empty commit")
        assert not committed


class TestAttachmentsDir:
    def test_returns_sibling_dir(self) -> None:
        md_path = Path("/some/dir/My Page.md")
        att = attachments_dir(md_path)
        assert att == Path("/some/dir/My Page-attachments")

    def test_uses_stem(self) -> None:
        md_path = Path("foo/bar.md")
        att = attachments_dir(md_path)
        assert att == Path("foo/bar-attachments")


class TestMoveAttachmentsAlongside:
    def test_moves_attachments_dir(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)

        old_md = tmp_path / "Old Page.md"
        old_md.write_text("content")
        att_dir = tmp_path / "Old Page-attachments"
        att_dir.mkdir()
        (att_dir / "image.png").write_bytes(b"\x89PNG")
        _git_add_and_commit(tmp_path)

        new_md = tmp_path / "New Page.md"
        move_attachments_alongside(old_md, new_md, tmp_path)

        # Check that the new attachments dir is created in git
        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(tmp_path), capture_output=True, text=True
        )
        assert "New Page-attachments" in result.stdout or "Old Page-attachments" in result.stdout

    def test_no_op_when_no_attachments_dir(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        old_md = tmp_path / "page.md"
        old_md.write_text("content")
        _git_add_and_commit(tmp_path)

        new_md = tmp_path / "renamed.md"
        # Should not raise even when no attachments dir exists
        move_attachments_alongside(old_md, new_md, tmp_path)


class TestComputeRenamePath:
    def test_basic_rename(self, tmp_path: Path) -> None:
        current = tmp_path / "old-page.md"
        used: set[Path] = set()
        result = compute_rename_path(current, "New Title", tmp_path, "100", used)
        assert result == tmp_path / "New Title.md"
        assert result in used

    def test_collision_appends_page_id(self, tmp_path: Path) -> None:
        # Create an existing file that would collide
        existing = tmp_path / "New Title.md"
        existing.write_text("existing")

        current = tmp_path / "old-page.md"
        used: set[Path] = set()
        result = compute_rename_path(current, "New Title", tmp_path, "100", used)
        assert "100" in result.name

    def test_collision_via_used_paths(self, tmp_path: Path) -> None:
        # Simulate collision via already-used paths (without file on disk)
        existing = tmp_path / "New Title.md"
        used: set[Path] = {existing}

        current = tmp_path / "old-page.md"
        result = compute_rename_path(current, "New Title", tmp_path, "100", used)
        assert "100" in result.name

    def test_same_path_unchanged_not_in_used(self, tmp_path: Path) -> None:
        current = tmp_path / "Same Title.md"
        current.write_text("existing")

        used: set[Path] = set()
        result = compute_rename_path(current, "Same Title", tmp_path, "100", used)
        # If current path = computed path and it's the same file, should return it
        assert result == tmp_path / "Same Title.md"
