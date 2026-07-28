"""Tests for mdd.mirror.orchestrator — generic commit-and-push (spec S44)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from mdd.mirror.errors import MirrorError
from mdd.mirror.git import GenericGitBackend
from mdd.mirror.orchestrator import commit_and_push

if TYPE_CHECKING:
    from pathlib import Path


def _init_repo(path: Path) -> None:
    _ = subprocess.run(["git", "init", "-b", "main"], cwd=str(path), check=True)
    _ = subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(path), check=True)
    _ = subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(path), check=True)


class TestCommitOnly:
    def test_clean_tree_is_no_op(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "seed.md").write_text("seed")
        _ = subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
        _ = subprocess.run(["git", "commit", "-m", "seed"], cwd=str(tmp_path), check=True)

        result = commit_and_push(tmp_path, commit_message="m", backend=GenericGitBackend())
        assert result.committed is False
        assert result.pushed is False
        assert result.errors == []

    def test_dirty_tree_commits(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "page.md").write_text("new")

        result = commit_and_push(
            tmp_path, commit_message="chore: sync", backend=GenericGitBackend()
        )
        assert result.committed is True
        assert result.commit_sha
        assert result.pushed is False

    def test_refuses_when_not_a_repo_and_not_pushing(self, tmp_path: Path) -> None:
        with pytest.raises(MirrorError, match="not a git repository"):
            commit_and_push(tmp_path, commit_message="m", backend=GenericGitBackend())


class TestPushRoundTrip:
    def test_push_to_local_bare_remote(self, tmp_path: Path) -> None:
        remote = tmp_path / "remote.git"
        _ = subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True)
        work = tmp_path / "work"
        _ = subprocess.run(["git", "clone", str(remote), str(work)], check=True)
        _ = subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(work), check=True)
        _ = subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(work), check=True)
        (work / "page.md").write_text("hello")

        result = commit_and_push(
            work, commit_message="chore: first sync", backend=GenericGitBackend(), push=True
        )
        assert result.committed is True
        assert result.pushed is True
        assert result.errors == []

        log = subprocess.run(
            ["git", "log", "--oneline", "-1", "main"],
            cwd=str(remote),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "chore: first sync" in log

    def test_push_failure_recorded_as_error(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "page.md").write_text("dirty")
        # No 'origin' remote configured → the generic push fails; the
        # orchestrator records it rather than raising.
        result = commit_and_push(
            tmp_path, commit_message="chore: sync", backend=GenericGitBackend(), push=True
        )
        assert result.committed is True
        assert result.pushed is False
        assert any("push:" in e for e in result.errors)
