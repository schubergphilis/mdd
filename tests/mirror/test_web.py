"""Tests for mdd.mirror.web — the browse-URL plumbing backends share (spec S44).

These moved here from tests/confluence/test_header.py when the footer stopped
holding a host of its own and started asking the registered backend.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

from mdd.mirror.web import GITHUB_BLOB_INFIX, clone_url_to_web, git_blob_url

if TYPE_CHECKING:
    from pathlib import Path

_HOST = "gitlab.example.com"


class TestCloneUrlToWeb:
    def test_ssh_url(self) -> None:
        result = clone_url_to_web(
            "git@gitlab.example.com:mdd/confluence/SPACE.git", allowed_host=_HOST
        )
        assert result == "https://gitlab.example.com/mdd/confluence/SPACE"

    def test_https_url_with_git_suffix(self) -> None:
        result = clone_url_to_web(
            "https://gitlab.example.com/mdd/confluence/SPACE.git", allowed_host=_HOST
        )
        assert result == "https://gitlab.example.com/mdd/confluence/SPACE"

    def test_https_url_without_suffix(self) -> None:
        result = clone_url_to_web(
            "https://gitlab.example.com/mdd/confluence/SPACE", allowed_host=_HOST
        )
        assert result == "https://gitlab.example.com/mdd/confluence/SPACE"

    def test_unknown_url_returns_none(self) -> None:
        result = clone_url_to_web("ftp://example.com/repo", allowed_host=_HOST)
        assert result is None

    def test_ssh_url_on_other_host_returns_none(self) -> None:
        """A host outside the backend's own must be rejected."""
        result = clone_url_to_web("git@github.com:foo/bar.git", allowed_host=_HOST)
        assert result is None

    def test_https_url_on_other_host_returns_none(self) -> None:
        result = clone_url_to_web("https://github.com/foo/bar.git", allowed_host=_HOST)
        assert result is None

    def test_host_is_matched_case_insensitively(self) -> None:
        result = clone_url_to_web("git@GitLab.Example.COM:mdd/repo.git", allowed_host=_HOST)
        assert result == "https://gitlab.example.com/mdd/repo"

    def test_allowed_host_selects_the_instance(self) -> None:
        result = clone_url_to_web(
            "git@other.gitlab.example.com:mdd/repo.git",
            allowed_host="other.gitlab.example.com",
        )
        assert result == "https://other.gitlab.example.com/mdd/repo"


class TestGitBlobUrl:
    def _make_fake_run(self, tmp_path: Path, *, remote_url: str, branch: str = "main"):  # type: ignore[no-untyped-def]
        """Return a fake subprocess.run callable standing in for the git calls."""

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if "get-url" in cmd:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout=remote_url + "\n")
            if "--show-toplevel" in cmd:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout=str(tmp_path) + "\n")
            if "symbolic-ref" in cmd:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout=branch + "\n")
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="")

        return fake_run

    def test_returns_none_when_git_not_available(self, tmp_path: Path) -> None:
        md_path = tmp_path / "Page.md"
        md_path.write_text("# Test")
        with patch("mdd.mirror.web.subprocess.run", side_effect=FileNotFoundError):
            result = git_blob_url(md_path, allowed_host=_HOST)
        assert result is None

    def test_returns_none_when_no_remote(self, tmp_path: Path) -> None:
        md_path = tmp_path / "Page.md"
        md_path.write_text("# Test")

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="")

        with patch("mdd.mirror.web.subprocess.run", side_effect=fake_run):
            result = git_blob_url(md_path, allowed_host=_HOST)
        assert result is None

    def test_returns_url_when_git_remote_present(self, tmp_path: Path) -> None:
        md_path = tmp_path / "subdir" / "Page.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("# Test")

        remote = "git@gitlab.example.com:mdd/confluence/SPACE.git"
        fake_run = self._make_fake_run(tmp_path, remote_url=remote)

        with patch("mdd.mirror.web.subprocess.run", side_effect=fake_run):
            result = git_blob_url(md_path, allowed_host=_HOST)

        assert (
            result == "https://gitlab.example.com/mdd/confluence/SPACE/-/blob/main/subdir/Page.md"
        )

    def test_blob_infix_is_selectable(self, tmp_path: Path) -> None:
        """A GitHub-shaped backend passes its own infix; no `/-/` segment."""
        md_path = tmp_path / "Page.md"
        md_path.write_text("# Test")

        fake_run = self._make_fake_run(tmp_path, remote_url="git@github.com:foo/bar.git")

        with patch("mdd.mirror.web.subprocess.run", side_effect=fake_run):
            result = git_blob_url(md_path, allowed_host="github.com", blob_infix=GITHUB_BLOB_INFIX)

        assert result == "https://github.com/foo/bar/blob/main/Page.md"

    def test_branch_from_git_is_used(self, tmp_path: Path) -> None:
        md_path = tmp_path / "Page.md"
        md_path.write_text("# Test")

        remote = "git@gitlab.example.com:mdd/confluence/SPACE.git"
        fake_run = self._make_fake_run(tmp_path, remote_url=remote, branch="develop")

        with patch("mdd.mirror.web.subprocess.run", side_effect=fake_run):
            result = git_blob_url(md_path, allowed_host=_HOST)

        assert result is not None
        assert "/-/blob/develop/" in result
        assert "/-/blob/main/" not in result

    def test_detached_head_falls_back_to_main(self, tmp_path: Path) -> None:
        md_path = tmp_path / "Page.md"
        md_path.write_text("# Test")

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if "get-url" in cmd:
                return subprocess.CompletedProcess(
                    cmd, returncode=0, stdout="git@gitlab.example.com:mdd/confluence/SPACE.git\n"
                )
            if "--show-toplevel" in cmd:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout=str(tmp_path) + "\n")
            # `git symbolic-ref` fails on a detached HEAD.
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="")

        with patch("mdd.mirror.web.subprocess.run", side_effect=fake_run):
            result = git_blob_url(md_path, allowed_host=_HOST)

        assert result is not None
        assert "/-/blob/main/Page.md" in result

    def test_remote_on_other_host_returns_none(self, tmp_path: Path) -> None:
        """A remote on a different host must return None (S09 footers link to the mirror)."""
        md_path = tmp_path / "Page.md"
        md_path.write_text("# Test")

        fake_run = self._make_fake_run(tmp_path, remote_url="git@github.com:foo/bar.git")

        with patch("mdd.mirror.web.subprocess.run", side_effect=fake_run):
            result = git_blob_url(md_path, allowed_host=_HOST)

        assert result is None

    def test_file_outside_the_work_tree_returns_none(self, tmp_path: Path) -> None:
        """A path that is not under the reported toplevel cannot be linked."""
        md_path = tmp_path / "Page.md"
        md_path.write_text("# Test")

        elsewhere = tmp_path / "other-repo"
        elsewhere.mkdir()
        fake_run = self._make_fake_run(
            elsewhere, remote_url="git@gitlab.example.com:mdd/confluence/SPACE.git"
        )

        with patch("mdd.mirror.web.subprocess.run", side_effect=fake_run):
            result = git_blob_url(md_path, allowed_host=_HOST)

        assert result is None

    def test_spaces_in_path_are_percent_encoded(self, tmp_path: Path) -> None:
        """Multi-word titles yield paths with spaces; the URL must percent-encode them."""
        md_path = tmp_path / "Labs Home" / "Demoes" / "Connected Ship.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("# Test")

        remote = "git@gitlab.example.com:mdd/confluence/Labs-Non-Prod.git"
        fake_run = self._make_fake_run(tmp_path, remote_url=remote)

        with patch("mdd.mirror.web.subprocess.run", side_effect=fake_run):
            result = git_blob_url(md_path, allowed_host=_HOST)

        assert result is not None
        assert " " not in result
        assert "/-/blob/main/Labs%20Home/Demoes/Connected%20Ship.md" in result

    def test_special_chars_in_branch_are_percent_encoded(self, tmp_path: Path) -> None:
        """A branch name with a slash or space must be encoded in the URL."""
        md_path = tmp_path / "Page.md"
        md_path.write_text("# Test")

        remote = "git@gitlab.example.com:mdd/confluence/SPACE.git"
        fake_run = self._make_fake_run(tmp_path, remote_url=remote, branch="feat/my branch")

        with patch("mdd.mirror.web.subprocess.run", side_effect=fake_run):
            result = git_blob_url(md_path, allowed_host=_HOST)

        assert result is not None
        assert "/-/blob/feat%2Fmy%20branch/Page.md" in result
