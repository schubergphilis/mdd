"""Tests for mdd.utils.git — shared git subprocess helpers."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from mdd.utils.git import GitError, is_dirty, is_git_repo, run_git

if TYPE_CHECKING:
    from pathlib import Path


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


class TestRunGit:
    def test_success_returns_completed_process(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _completed(stdout="ok\n")
            result = run_git(["status"], tmp_path)
        assert result.stdout == "ok\n"
        # Verify it shell-quoted the args and prefixed "git"
        call_args = mock_run.call_args
        assert call_args.args[0] == ["git", "status"]
        assert call_args.kwargs["cwd"] == str(tmp_path)
        assert call_args.kwargs["timeout"] == 30

    def test_custom_timeout_propagates(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _completed()
            run_git(["push"], tmp_path, timeout=60)
        assert mock_run.call_args.kwargs["timeout"] == 60

    def test_non_zero_exit_raises_git_error(self, tmp_path: Path) -> None:
        with (
            patch("subprocess.run", return_value=_completed(returncode=128, stderr="not a repo")),
            pytest.raises(GitError, match=r"status.*exit 128.*not a repo"),
        ):
            run_git(["status"], tmp_path)

    def test_file_not_found_raises_git_error(self, tmp_path: Path) -> None:
        with (
            patch("subprocess.run", side_effect=FileNotFoundError("no git")),
            pytest.raises(GitError, match="git is not installed"),
        ):
            run_git(["status"], tmp_path)

    def test_timeout_raises_git_error(self, tmp_path: Path) -> None:
        exc = subprocess.TimeoutExpired(cmd=["git", "push"], timeout=30)
        with (
            patch("subprocess.run", side_effect=exc),
            pytest.raises(GitError, match=r"push.*timed out after 30s"),
        ):
            run_git(["push"], tmp_path)

    def test_git_error_chains_original(self, tmp_path: Path) -> None:
        original = FileNotFoundError("no git")
        with patch("subprocess.run", side_effect=original), pytest.raises(GitError) as exc_info:
            run_git(["status"], tmp_path)
        assert exc_info.value.__cause__ is original


class TestIsDirty:
    def test_clean_tree(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _completed(stdout="")
            assert is_dirty(tmp_path) is False

    def test_dirty_tree(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _completed(stdout=" M foo.md\n")
            assert is_dirty(tmp_path) is True

    def test_git_not_installed_returns_false(self, tmp_path: Path) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert is_dirty(tmp_path) is False

    def test_non_zero_exit_returns_false(self, tmp_path: Path) -> None:
        # Not a git repo: git status --porcelain exits 128.
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _completed(returncode=128, stdout="")
            assert is_dirty(tmp_path) is False


class TestIsGitRepo:
    def test_missing_path_returns_false(self, tmp_path: Path) -> None:
        assert is_git_repo(tmp_path / "does-not-exist") is False

    def test_inside_work_tree(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _completed(stdout="true\n")
            assert is_git_repo(tmp_path) is True

    def test_not_a_repo_returns_false(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _completed(returncode=128, stdout="")
            assert is_git_repo(tmp_path) is False

    def test_git_not_installed_returns_false(self, tmp_path: Path) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert is_git_repo(tmp_path) is False
