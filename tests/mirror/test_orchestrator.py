"""Tests for mdd.mirror.orchestrator — generic commit-and-push (spec S44)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mdd.mirror.errors import MirrorError
from mdd.mirror.git import GenericGitBackend
from mdd.mirror.orchestrator import CommitAndPushResult, commit_and_push, git_commit
from mdd.mirror.protocol import MirrorTarget
from tests.mirror_stub import STUB_GROUP, STUB_HOST, StubBackend

if TYPE_CHECKING:
    from pathlib import Path


def _init_repo(path: Path) -> None:
    _ = subprocess.run(["git", "init", "-b", "main"], cwd=str(path), check=True)
    _ = subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(path), check=True)
    _ = subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(path), check=True)


def _initial_commit(path: Path) -> None:
    _ = (path / "seed.md").write_text("seed")
    _ = subprocess.run(["git", "add", "-A"], cwd=str(path), check=True)
    _ = subprocess.run(["git", "commit", "-m", "seed"], cwd=str(path), check=True)


def _cp(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    """Build a fake ``CompletedProcess`` for stubbing ``run_git_lenient``."""
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestGitCommit:
    def test_commits_pending_changes(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _initial_commit(tmp_path)
        _ = (tmp_path / "page.md").write_text("hello")

        committed, sha = git_commit(tmp_path, "test commit")

        assert committed is True
        assert sha
        log = subprocess.run(
            ["git", "log", "--oneline", "-1"], cwd=str(tmp_path), capture_output=True, text=True
        ).stdout
        assert "test commit" in log

    def test_nothing_to_commit_returns_false(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _initial_commit(tmp_path)

        committed, sha = git_commit(tmp_path, "no-op")
        assert committed is False
        assert sha == ""

    def test_non_repo_short_circuits(self, tmp_path: Path) -> None:
        # ``git status`` in a non-repo exits non-zero; the porcelain
        # pre-check short-circuits with (False, "") rather than raising.
        committed, sha = git_commit(tmp_path, "msg")
        assert committed is False
        assert sha == ""


class TestGitCommitUnreadableFiles:
    """``git_commit`` tolerates ``git add`` skipping unreadable files.

    CI runs as root on Linux, where ``chmod 000`` doesn't actually make a
    file unreadable (root bypasses permissions), so these tests stub
    ``run_git_lenient`` to reproduce git's real behaviour for
    ``add -A --ignore-errors``: non-zero exit, but readable files staged.
    """

    def test_partial_add_failure_with_staged_content_still_commits(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        responses = [
            _cp(0, stdout=" M readable.md\n?? unreadable.md\n"),  # status --porcelain
            _cp(
                1,
                stderr='error: open("unreadable.md"): Operation not permitted\n'
                "error: unable to index file 'unreadable.md'\n",
            ),  # add -A --ignore-errors
            _cp(0, stdout=" readable.md | 1 +\n"),  # diff --cached --stat
            _cp(0),  # commit
            _cp(0, stdout="deadbeef\n"),  # rev-parse HEAD
        ]

        with (
            patch("mdd.mirror.orchestrator.run_git_lenient", side_effect=responses) as mock_run,
            caplog.at_level("WARNING"),
        ):
            committed, sha = git_commit(tmp_path, "msg")

        assert committed is True
        assert sha == "deadbeef"
        assert mock_run.call_count == 5
        assert "unreadable.md" in caplog.text

    def test_add_failure_with_nothing_staged_raises(self, tmp_path: Path) -> None:
        responses = [
            _cp(0, stdout="?? unreadable.md\n"),  # status --porcelain
            _cp(1, stderr='error: open("unreadable.md"): Operation not permitted\n'),  # add
            _cp(0, stdout=""),  # diff --cached --stat: nothing staged
        ]

        with (
            patch("mdd.mirror.orchestrator.run_git_lenient", side_effect=responses),
            pytest.raises(MirrorError, match="git add failed"),
        ):
            git_commit(tmp_path, "msg")


class TestCommitAndPushResultDefaults:
    def test_dataclass_default_values(self) -> None:
        r = CommitAndPushResult()
        assert r.committed is False
        assert r.commit_sha == ""
        assert r.pushed is False
        assert r.bootstrapped is False
        assert r.errors == []


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

    def test_no_push_skips_push_steps(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _initial_commit(tmp_path)
        _ = (tmp_path / "page.md").write_text("dirty")

        backend = StubBackend()
        result = commit_and_push(tmp_path, commit_message="msg", backend=backend)

        assert result.committed is True
        assert result.pushed is False
        assert backend.pushes == []
        assert backend.ensured == []


class TestTargetedPush:
    """Push with a *target*: the backend resolves, ensures and pushes."""

    def test_cold_start_bootstraps_and_pushes(self, tmp_path: Path) -> None:
        """No git work-tree yet: bootstrap it from the backend's remote URL."""
        _ = (tmp_path / "doc.md").write_text("doc")
        backend = StubBackend()

        with patch.dict(
            "os.environ",
            {
                "GIT_AUTHOR_NAME": "T",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "T",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        ):
            result = commit_and_push(
                tmp_path,
                commit_message="chore: first sync",
                backend=backend,
                target=MirrorTarget(kind="lucid", key="Labs"),
                push=True,
            )

        assert result.bootstrapped is True
        assert result.committed is True
        assert result.pushed is True
        assert result.errors == []
        # Bootstrap really happened: .git exists with origin pointing at the
        # URL the backend resolved.
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert url == f"https://{STUB_HOST}/{STUB_GROUP}/Labs.git"
        assert [t.key for t in backend.ensured] == ["Labs"]
        assert [p for p, _ in backend.pushes] == [tmp_path]

    def test_warm_start_ensures_remote_then_pushes(self, tmp_path: Path) -> None:
        """Work-tree exists; the remote is still verified before pushing."""
        _init_repo(tmp_path)
        _initial_commit(tmp_path)
        _ = (tmp_path / "page.md").write_text("dirty")

        backend = StubBackend()
        result = commit_and_push(
            tmp_path,
            commit_message="chore: sync",
            backend=backend,
            target=MirrorTarget(kind="confluence", key="TEST"),
            push=True,
        )

        assert result.bootstrapped is False
        assert result.committed is True
        assert result.pushed is True
        assert [t.key for t in backend.ensured] == ["TEST"]
        assert [p for p, _ in backend.pushes] == [tmp_path]
