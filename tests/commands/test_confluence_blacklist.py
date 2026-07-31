"""CLI behaviour when the confidentiality blacklist refuses a Confluence space.

A refusal must surface as a logged error and exit code 1, not a traceback.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from mdd.cli import main as _cli_main
from mdd.confluence.client import ConfluenceClient
from mdd.utils.blacklist import BlacklistError

if TYPE_CHECKING:
    from pathlib import Path


def cmd_confluence(args: list[str]) -> int:
    return _cli_main(["confluence", *args])


def _enter(self: object) -> object:
    return self


def _make_mock_client() -> MagicMock:
    client = MagicMock(spec=ConfluenceClient)
    client.__enter__ = _enter
    client.__exit__ = MagicMock(return_value=False)
    return client


def _make_config() -> MagicMock:
    config = MagicMock()
    config.url = "https://example.atlassian.net"
    config.username = "user@example.com"
    config.api_token = "test-token"
    return config


@pytest.fixture(autouse=True)
def blacklist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make ``PRIVATE`` the only protected space, from a known file."""
    f = tmp_path / "data-protection.yaml"
    f.write_text(
        textwrap.dedent(
            """\
            confluence:
              blacklisted_spaces:
                - PRIVATE
            sharepoint:
              blacklisted_sites: []
            """
        )
    )
    monkeypatch.setattr("mdd.utils.config._repo_blacklist_path", lambda: f)
    monkeypatch.setattr("mdd.utils.config.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    return f


class TestSyncSpaceRefusal:
    def test_exit_code_one_and_error_on_stderr(
        self, tmp_path: Path, blacklist: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch("mdd.commands.confluence.load_config", return_value=_make_config()),
            patch("mdd.commands.confluence.ConfluenceClient", return_value=_make_mock_client()),
        ):
            rc = cmd_confluence(["sync-space", "PRIVATE", "--output", str(tmp_path / "mirror")])

        assert rc == 1
        msgs = capsys.readouterr().err
        assert "blacklist" in msgs
        assert "PRIVATE" in msgs
        # The operator is told which file to edit.
        assert str(blacklist) in msgs


class TestExportPageRefusal:
    def test_exit_code_one_and_error_on_stderr(
        self, tmp_path: Path, blacklist: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        client = _make_mock_client()
        client.get_page.return_value = {
            "id": "12345",
            "title": "Secret",
            "status": "current",
            "spaceId": "98306",
            "spaceKey": "PRIVATE",
            "parentId": None,
            "version": {"number": 1, "createdAt": "2026-01-01T00:00:00Z"},
            "body": {"storage": {"value": "<p>Secret.</p>"}},
            "_links": {"webui": "/wiki/spaces/PRIVATE/pages/12345/Secret"},
        }
        out_dir = tmp_path / "out"
        with (
            patch("mdd.commands.confluence.load_config", return_value=_make_config()),
            patch("mdd.commands.confluence.ConfluenceClient", return_value=client),
        ):
            rc = cmd_confluence(["export-page", "12345", "--output", str(out_dir)])

        assert rc == 1
        msgs = capsys.readouterr().err
        assert "blacklist" in msgs
        assert "PRIVATE" in msgs
        assert not out_dir.exists()


class TestMutateRefusal:
    """The mutate commands can materialise ancestors, so they reach the gate."""

    @pytest.mark.parametrize(
        ("subcommand", "target", "extra"),
        [
            ("rename-page", "mdd.commands.confluence.rename_page", ["New Title"]),
            ("move-page", "mdd.commands.confluence.move_page", ["--parent", "999"]),
            ("archive-page", "mdd.commands.confluence.archive_page", []),
            ("unarchive-page", "mdd.commands.confluence.unarchive_page", []),
        ],
    )
    def test_refusal_becomes_exit_one(
        self,
        tmp_path: Path,
        blacklist: Path,
        capsys: pytest.CaptureFixture[str],
        subcommand: str,
        target: str,
        extra: list[str],
    ) -> None:
        md_path = tmp_path / "page.md"
        md_path.write_text("---\nconfluence:\n  page_id: '1'\n---\n\n# Page\n")
        refusal = BlacklistError("Confluence space 'PRIVATE' matches blacklist pattern 'PRIVATE'.")
        with (
            patch("mdd.commands.confluence.load_config", return_value=_make_config()),
            patch(target, side_effect=refusal),
        ):
            rc = cmd_confluence([subcommand, str(md_path), *extra])

        assert rc == 1
        assert "blacklist" in capsys.readouterr().err


class TestMissingConfigRefusal:
    def test_no_blacklist_file_exits_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Fail closed: with no data-protection config at all, sync refuses to run."""
        monkeypatch.setattr("mdd.utils.config._repo_blacklist_path", lambda: None)
        with (
            patch("mdd.commands.confluence.load_config", return_value=_make_config()),
            patch("mdd.commands.confluence.ConfluenceClient", return_value=_make_mock_client()),
        ):
            rc = cmd_confluence(["sync-space", "ENG", "--output", str(tmp_path / "mirror")])

        assert rc == 1
        msgs = capsys.readouterr().err
        assert "blacklist config" in msgs
        assert "No data-protection blacklist found" in msgs
