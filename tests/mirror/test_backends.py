"""Contract tests for the built-in mirror backends."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from mdd.mirror import git as git_module
from mdd.mirror.git import GenericGitBackend, MirrorPushError
from mdd.mirror.local import LocalOnlyBackend
from mdd.mirror.protocol import MirrorTarget

if TYPE_CHECKING:
    from pathlib import Path


_TARGET = MirrorTarget(kind="confluence", key="TEST")


class TestLocalOnlyBackend:
    def test_resolve_remote_is_none(self) -> None:
        assert LocalOnlyBackend().resolve_remote(_TARGET) is None

    def test_ensure_remote_reports_exists(self) -> None:
        assert LocalOnlyBackend().ensure_remote(_TARGET).status == "exists"

    def test_guard_is_noop(self, tmp_path: Path) -> None:
        LocalOnlyBackend().guard_remote(tmp_path)  # does not raise

    def test_not_reachable(self) -> None:
        assert LocalOnlyBackend().reachable() is False

    def test_web_url_is_none(self, tmp_path: Path) -> None:
        assert LocalOnlyBackend().web_url(tmp_path / "Page.md") is None

    def test_push_is_a_misuse(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="no remote"):
            LocalOnlyBackend().push(tmp_path)


class TestGenericGitBackend:
    def test_resolve_remote_is_none(self) -> None:
        assert GenericGitBackend().resolve_remote(_TARGET) is None

    def test_ensure_remote_reports_exists(self) -> None:
        assert GenericGitBackend().ensure_remote(_TARGET).status == "exists"

    def test_guard_is_noop(self, tmp_path: Path) -> None:
        GenericGitBackend().guard_remote(tmp_path)  # does not raise

    def test_reachable(self) -> None:
        assert GenericGitBackend().reachable() is True

    def test_web_url_is_none(self, tmp_path: Path) -> None:
        """No browse convention is guessed for a plain git remote."""
        assert GenericGitBackend().web_url(tmp_path / "Page.md") is None

    def test_push_refuses_non_repo(self, tmp_path: Path) -> None:
        with pytest.raises(MirrorPushError, match="not inside a git work-tree"):
            GenericGitBackend().push(tmp_path)

    def test_push_to_local_bare_remote_round_trips(self, tmp_path: Path) -> None:
        # A bare "remote" plus a working clone exercises the real push path
        # without any network or provider dependency.
        remote = tmp_path / "remote.git"
        _ = subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True)

        work = tmp_path / "work"
        _ = subprocess.run(["git", "clone", str(remote), str(work)], check=True)
        _ = subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(work), check=True)
        _ = subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(work), check=True)

        (work / "page.md").write_text("hello")
        GenericGitBackend().push(work, message="chore: first sync")

        # The bare remote now has the commit on main.
        log = subprocess.run(
            ["git", "log", "--oneline", "-1", "main"],
            cwd=str(remote),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "chore: first sync" in log


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    ).stdout


def _remote_with_refs(tmp_path: Path) -> Path:
    """A bare remote holding ``main``, a second branch ``keepme`` and a tag ``v1``."""
    remote = tmp_path / "remote.git"
    _ = subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True, capture_output=True
    )
    seed = tmp_path / "seed"
    _ = subprocess.run(
        ["git", "clone", "-q", str(remote), str(seed)], check=True, capture_output=True
    )
    _ = _git(
        seed, "-c", "user.name=T", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "seed"
    )
    _ = _git(seed, "push", "-q", "origin", "main")
    _ = _git(seed, "push", "-q", "origin", "main:keepme")
    _ = _git(seed, "tag", "v1")
    _ = _git(seed, "push", "-q", "origin", "v1")
    return remote


def _clone(remote: Path, work: Path) -> Path:
    _ = subprocess.run(
        ["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True
    )
    _ = _git(work, "config", "user.email", "t@t")
    _ = _git(work, "config", "user.name", "Tester")
    return work


def _check_out_dash_branch(work: Path, name: str) -> None:
    """Check out a branch whose name starts with ``-``.

    ``git branch`` refuses such names, but the full ref is valid, so it is
    created the way a clone would receive it.
    """
    _ = _git(work, "update-ref", f"refs/heads/{name}", "HEAD")
    _ = _git(work, "symbolic-ref", "HEAD", f"refs/heads/{name}")


class TestGenericGitBackendBranchName:
    def test_first_push_argv_ends_options_before_remote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[list[str]] = []

        def fake_run_git(
            args: list[str], cwd: Path, *, timeout: int = 30
        ) -> subprocess.CompletedProcess[str]:
            del cwd, timeout
            calls.append(args)
            if args[:2] == ["rev-parse", "--abbrev-ref"] and args[-1] == "@{u}":
                raise git_module.GitError("no upstream")
            stdout = "feature\n" if args == ["rev-parse", "--abbrev-ref", "HEAD"] else ""
            return subprocess.CompletedProcess(args, 0, stdout, "")

        monkeypatch.setattr(git_module, "run_git", fake_run_git)
        git_module._pull_and_push(tmp_path)  # pyright: ignore[reportPrivateUsage]
        assert calls[-1] == ["push", "-u", "--end-of-options", "origin", "feature"]

    def test_dash_named_branch_is_refused_and_remote_untouched(self, tmp_path: Path) -> None:
        remote = _remote_with_refs(tmp_path)
        before = _git(remote, "show-ref")
        work = _clone(remote, tmp_path / "work")
        _check_out_dash_branch(work, "--mirror")

        with pytest.raises(MirrorPushError, match="'--mirror' is not a valid branch name"):
            GenericGitBackend().push(work)

        assert _git(remote, "show-ref") == before

    def test_dash_named_branch_pushes_literally_past_end_of_options(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With the name check bypassed, the installed git must still read the
        # name as a refspec: the remote gains a branch called ``--mirror``
        # and keeps every ref it had.
        remote = _remote_with_refs(tmp_path)
        work = _clone(remote, tmp_path / "work")
        _check_out_dash_branch(work, "--mirror")

        def dash_branch(_path: Path) -> str:
            return "--mirror"

        monkeypatch.setattr(git_module, "_pushable_branch", dash_branch)

        git_module._pull_and_push(work)  # pyright: ignore[reportPrivateUsage]

        refs = _git(remote, "show-ref")
        assert "refs/heads/--mirror" in refs
        assert "refs/heads/keepme" in refs
        assert "refs/tags/v1" in refs

    def test_detached_head_is_refused(self, tmp_path: Path) -> None:
        remote = _remote_with_refs(tmp_path)
        before = _git(remote, "show-ref")
        work = _clone(remote, tmp_path / "work")
        _ = _git(work, "checkout", "-q", "--detach")

        with pytest.raises(MirrorPushError, match="HEAD is detached"):
            GenericGitBackend().push(work)

        assert _git(remote, "show-ref") == before

    def test_new_branch_without_upstream_is_pushed(self, tmp_path: Path) -> None:
        remote = _remote_with_refs(tmp_path)
        work = _clone(remote, tmp_path / "work")
        _ = _git(work, "checkout", "-q", "-b", "feature/sync")
        (work / "page.md").write_text("hello")

        GenericGitBackend().push(work, message="chore: sync")

        assert "chore: sync" in _git(remote, "log", "--oneline", "-1", "feature/sync")
        assert _git(work, "rev-parse", "--abbrev-ref", "@{u}").strip() == "origin/feature/sync"

    @pytest.mark.parametrize(("name", "valid"), [("main", True), ("a..b", False), ("a b", False)])
    def test_branch_name_check(self, tmp_path: Path, name: str, *, valid: bool) -> None:
        assert git_module._is_valid_branch_name(name, tmp_path) is valid  # pyright: ignore[reportPrivateUsage]
