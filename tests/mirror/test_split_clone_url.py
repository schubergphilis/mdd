"""Tests for mdd.mirror.web.split_clone_url — the shared clone-URL parser."""

from __future__ import annotations

import pytest

from mdd.mirror.web import CloneUrlParts, split_clone_url


class TestSshForm:
    def test_namespace_and_repo(self) -> None:
        assert split_clone_url("git@gitlab.example.com:mdd/confluence/SPACE.git") == CloneUrlParts(
            host="gitlab.example.com",
            path="mdd/confluence/SPACE",
            namespace="mdd/confluence",
            repo="SPACE",
        )

    def test_git_suffix_is_optional(self) -> None:
        parts = split_clone_url("git@github.com:foo/bar")
        assert parts is not None
        assert parts.path == "foo/bar"

    def test_repo_at_root_has_empty_namespace(self) -> None:
        parts = split_clone_url("git@github.com:bar.git")
        assert parts is not None
        assert parts.namespace == ""
        assert parts.repo == "bar"

    def test_host_is_lower_cased(self) -> None:
        parts = split_clone_url("git@GitLab.Example.COM:mdd/repo.git")
        assert parts is not None
        assert parts.host == "gitlab.example.com"

    def test_never_carries_a_port(self) -> None:
        """The scp-like form has no syntax for one — the colon starts the path."""
        parts = split_clone_url("git@github.com:foo/bar.git")
        assert parts is not None
        assert parts.port is None


class TestHttpsForm:
    def test_with_git_suffix(self) -> None:
        assert split_clone_url("https://github.com/foo/bar.git") == CloneUrlParts(
            host="github.com", path="foo/bar", namespace="foo", repo="bar"
        )

    def test_without_git_suffix(self) -> None:
        parts = split_clone_url("https://github.com/foo/bar")
        assert parts is not None
        assert parts.path == "foo/bar"

    def test_trailing_slash_is_stripped(self) -> None:
        parts = split_clone_url("https://github.com/foo/bar/")
        assert parts is not None
        assert parts.path == "foo/bar"

    def test_port_is_captured(self) -> None:
        parts = split_clone_url("https://gitlab.example.com:8443/mdd/repo.git")
        assert parts is not None
        assert parts.host == "gitlab.example.com"
        assert parts.port == 8443

    def test_plain_http_is_accepted(self) -> None:
        parts = split_clone_url("http://gitlab.example.com/mdd/repo.git")
        assert parts is not None
        assert parts.path == "mdd/repo"


class TestUnrecognised:
    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com/repo",
            "ssh://git@github.com:22/foo/bar.git",
            "/srv/git/bare.git",
            "https://github.com/",
            "",
        ],
    )
    def test_returns_none(self, url: str) -> None:
        assert split_clone_url(url) is None


def test_surrounding_whitespace_is_ignored() -> None:
    """`git remote get-url` output arrives with a trailing newline."""
    parts = split_clone_url("  git@github.com:foo/bar.git\n")
    assert parts is not None
    assert parts.repo == "bar"
