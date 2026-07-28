"""Contract tests for the built-in mirror backends (spec S44)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

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
        """No browse convention is guessed for a plain git remote (S44)."""
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
