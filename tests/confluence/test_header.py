"""Tests for mdd.confluence.header"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

from mdd.confluence.header import (
    clone_url_to_web,
    get_gitlab_url,
    insert_mdd_footer,
    strip_export_header,
    strip_export_title_h1,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestStripExportHeader:
    def test_removes_leading_export_callout(self) -> None:
        body = (
            "> **Confluence export**\n"
            ">\n"
            "> This page was exported from confluence page [My Page](https://example.com)\n"
            "> on 2024-01-01. Check Confluence for the most up-to-date version.\n"
            "\n"
            "## Real content\n"
            "\n"
            "Some text here.\n"
        )
        result = strip_export_header(body)
        assert "**Confluence export**" not in result
        assert "## Real content" in result
        assert "Some text here." in result

    def test_leaves_later_blockquotes_intact(self) -> None:
        body = (
            "> **Confluence export**\n"
            ">\n"
            "> Exported on 2024-01-01.\n"
            "\n"
            "Some intro text.\n"
            "\n"
            "> This is a real quote in the content.\n"
            "\n"
            "More text.\n"
        )
        result = strip_export_header(body)
        assert "This is a real quote in the content." in result
        assert "**Confluence export**" not in result

    def test_noop_when_no_export_header(self) -> None:
        body = "## Introduction\n\nSome content here.\n"
        result = strip_export_header(body)
        assert result == body

    def test_noop_when_blockquote_does_not_start_with_confluence_export(self) -> None:
        body = "> This is a regular quote.\n\nSome content.\n"
        result = strip_export_header(body)
        assert result == body

    def test_handles_leading_blank_lines(self) -> None:
        body = "\n\n> **Confluence export**\n>\n> Exported page.\n\nContent.\n"
        result = strip_export_header(body)
        assert "**Confluence export**" not in result
        assert "Content." in result

    def test_empty_body_returns_unchanged(self) -> None:
        assert strip_export_header("") == ""

    def test_removes_multiline_blockquote(self) -> None:
        body = "> **Confluence export**\n> Line 2\n> Line 3\n\nBody text.\n"
        result = strip_export_header(body)
        assert "**Confluence export**" not in result
        assert "Body text." in result


class TestStripExportTitleH1:
    """The export prepends ``# {title}`` so the markdown file is self-contained.

    On update, we must remove that leading H1 — the page title is the Confluence
    page meta, and re-emitting it as a body ``<h1>`` would duplicate the title.
    """

    def test_strips_matching_leading_h1(self) -> None:
        body = "# My Page\n\nFirst paragraph.\n"
        result = strip_export_title_h1(body, "My Page")
        assert result == "First paragraph.\n"

    def test_strips_with_leading_blank_lines(self) -> None:
        body = "\n\n# My Page\n\nContent.\n"
        result = strip_export_title_h1(body, "My Page")
        assert result == "Content.\n"

    def test_noop_when_no_h1(self) -> None:
        body = "First paragraph.\n\nSecond.\n"
        assert strip_export_title_h1(body, "My Page") == body

    def test_noop_when_h1_does_not_match_title(self) -> None:
        body = "# Some Other Heading\n\nContent.\n"
        assert strip_export_title_h1(body, "My Page") == body

    def test_noop_when_title_empty(self) -> None:
        body = "# My Page\n\nContent.\n"
        assert strip_export_title_h1(body, "") == body

    def test_noop_when_first_block_is_not_h1(self) -> None:
        body = "## Subsection\n\nContent.\n"
        assert strip_export_title_h1(body, "My Page") == body

    def test_only_strips_first_h1(self) -> None:
        body = "# My Page\n\nIntro.\n\n# My Page\n\nMore.\n"
        result = strip_export_title_h1(body, "My Page")
        assert result.count("# My Page") == 1
        assert result.startswith("Intro.")

    def test_title_with_special_characters(self) -> None:
        body = "# Realtime prototyping with stakeholders\n\nContent.\n"
        result = strip_export_title_h1(body, "Realtime prototyping with stakeholders")
        assert result == "Content.\n"

    def test_trailing_whitespace_on_h1_line_tolerated(self) -> None:
        body = "# My Page   \n\nContent.\n"
        result = strip_export_title_h1(body, "My Page")
        assert result == "Content.\n"

    def test_empty_body(self) -> None:
        assert strip_export_title_h1("", "My Page") == ""


class TestInsertMddFooter:
    _URL = "https://gitlab.example.com/mdd/confluence/SPACE/-/blob/main/Page.md"

    def test_appends_footer_when_absent(self) -> None:
        xhtml = "<p>Hello world</p>"
        result = insert_mdd_footer(xhtml, self._URL)
        assert "MDD markdown version of this page at" in result
        assert self._URL in result
        assert xhtml in result

    def test_replaces_existing_footer(self) -> None:
        old_url = "https://old.example.com/old.md"
        xhtml = (
            "<p>Content</p>\n"
            f"<p><sub><em>MDD markdown version of this page at "
            f'<a href="{old_url}">{old_url}</a></em></sub></p>'
        )
        result = insert_mdd_footer(xhtml, self._URL)
        assert old_url not in result
        assert self._URL in result
        # Should appear exactly once
        assert result.count("MDD markdown version of this page at") == 1

    def test_idempotent_second_call(self) -> None:
        xhtml = "<p>Content</p>"
        result1 = insert_mdd_footer(xhtml, self._URL)
        result2 = insert_mdd_footer(result1, self._URL)
        assert result2.count("MDD markdown version of this page at") == 1

    def test_warns_and_returns_unchanged_when_no_url(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        xhtml = "<p>Content</p>"
        with caplog.at_level("WARNING", logger="mdd.confluence.header"):
            result = insert_mdd_footer(xhtml, None)
        assert result == xhtml
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "GitLab" in msgs or "footer" in msgs

    def test_footer_structure(self) -> None:
        xhtml = "<p>Content</p>"
        result = insert_mdd_footer(xhtml, self._URL)
        assert "<p><sub><em>" in result
        assert "</em></sub></p>" in result
        assert "<a href=" in result


class TestCloneUrlToWeb:
    def test_ssh_url(self) -> None:
        result = clone_url_to_web("git@gitlab.example.com:mdd/confluence/SPACE.git")
        assert result == "https://gitlab.example.com/mdd/confluence/SPACE"

    def test_https_url_with_git_suffix(self) -> None:
        result = clone_url_to_web("https://gitlab.example.com/mdd/confluence/SPACE.git")
        assert result == "https://gitlab.example.com/mdd/confluence/SPACE"

    def test_https_url_without_suffix(self) -> None:
        result = clone_url_to_web("https://gitlab.example.com/mdd/confluence/SPACE")
        assert result == "https://gitlab.example.com/mdd/confluence/SPACE"

    def test_unknown_url_returns_none(self) -> None:
        result = clone_url_to_web("ftp://example.com/repo")
        assert result is None

    def test_github_ssh_url_returns_none(self) -> None:
        """A host outside the configured allow-list must be rejected."""
        result = clone_url_to_web("git@github.com:foo/bar.git")
        assert result is None

    def test_github_https_url_returns_none(self) -> None:
        result = clone_url_to_web("https://github.com/foo/bar.git")
        assert result is None

    def test_allowed_host_override(self) -> None:
        """allowed_host parameter allows other GitLab instances."""
        result = clone_url_to_web(
            "git@other.gitlab.example.com:mdd/repo.git",
            allowed_host="other.gitlab.example.com",
        )
        assert result == "https://other.gitlab.example.com/mdd/repo"


class TestGetGitlabUrl:
    def _make_fake_run(self, tmp_path: Path, *, remote_url: str, branch: str = "main"):  # type: ignore[no-untyped-def]
        """Return a fake subprocess.run callable for get_gitlab_url tests."""

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
        with patch(
            "mdd.confluence.header.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = get_gitlab_url(md_path)
        assert result is None

    def test_returns_none_when_no_remote(self, tmp_path: Path) -> None:
        md_path = tmp_path / "Page.md"
        md_path.write_text("# Test")

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="")

        with patch("mdd.confluence.header.subprocess.run", side_effect=fake_run):
            result = get_gitlab_url(md_path)
        assert result is None

    def test_returns_url_when_git_remote_present(self, tmp_path: Path) -> None:
        md_path = tmp_path / "subdir" / "Page.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("# Test")

        remote = "git@gitlab.example.com:mdd/confluence/SPACE.git"
        fake_run = self._make_fake_run(tmp_path, remote_url=remote)

        with patch("mdd.confluence.header.subprocess.run", side_effect=fake_run):
            result = get_gitlab_url(md_path)

        assert result is not None
        assert "https://gitlab.example.com/mdd/confluence/SPACE" in result
        assert "Page.md" in result
        assert "/-/blob/main/" in result

    def test_non_main_branch_included_in_url(self, tmp_path: Path) -> None:
        """The actual current branch should appear in the URL, not hard-coded 'main'."""
        md_path = tmp_path / "Page.md"
        md_path.write_text("# Test")

        remote = "git@gitlab.example.com:mdd/confluence/SPACE.git"
        fake_run = self._make_fake_run(tmp_path, remote_url=remote, branch="develop")

        with patch("mdd.confluence.header.subprocess.run", side_effect=fake_run):
            result = get_gitlab_url(md_path)

        assert result is not None
        assert "/-/blob/develop/" in result
        assert "/-/blob/main/" not in result

    def test_github_remote_returns_none(self, tmp_path: Path) -> None:
        """A remote on a different host must return None (S09 footers link to the mirror)."""
        md_path = tmp_path / "Page.md"
        md_path.write_text("# Test")

        fake_run = self._make_fake_run(tmp_path, remote_url="git@github.com:foo/bar.git")

        with patch("mdd.confluence.header.subprocess.run", side_effect=fake_run):
            result = get_gitlab_url(md_path)

        assert result is None

    def test_spaces_in_path_are_percent_encoded(self, tmp_path: Path) -> None:
        """Multi-word titles yield paths with spaces; the URL must percent-encode them."""
        md_path = tmp_path / "Labs Home" / "Demoes" / "Connected Ship.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("# Test")

        remote = "git@gitlab.example.com:mdd/confluence/Labs-Non-Prod.git"
        fake_run = self._make_fake_run(tmp_path, remote_url=remote)

        with patch("mdd.confluence.header.subprocess.run", side_effect=fake_run):
            result = get_gitlab_url(md_path)

        assert result is not None
        assert " " not in result
        assert "/-/blob/main/Labs%20Home/Demoes/Connected%20Ship.md" in result

    def test_special_chars_in_branch_are_percent_encoded(self, tmp_path: Path) -> None:
        """A branch name with a slash or space must be encoded in the URL."""
        md_path = tmp_path / "Page.md"
        md_path.write_text("# Test")

        remote = "git@gitlab.example.com:mdd/confluence/SPACE.git"
        fake_run = self._make_fake_run(tmp_path, remote_url=remote, branch="feat/my branch")

        with patch("mdd.confluence.header.subprocess.run", side_effect=fake_run):
            result = get_gitlab_url(md_path)

        assert result is not None
        assert "/-/blob/feat%2Fmy%20branch/Page.md" in result
