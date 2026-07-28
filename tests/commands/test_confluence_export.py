"""Tests for mdd.commands.confluence (CLI dispatcher) — export page."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mdd.cli import main as _cli_main
from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.utils.config import ConfigError

if TYPE_CHECKING:
    from pathlib import Path


def cmd_confluence(args: list[str]) -> int:
    """Test helper: invoke mdd confluence via argparse."""
    return _cli_main(["confluence", *args])


_SAMPLE_PAGE: dict[str, Any] = {
    "id": "12345",
    "title": "Test Page",
    "status": "current",
    "spaceId": "98306",
    "spaceKey": "SPACE",
    "parentId": None,
    "createdAt": "2024-01-01T00:00:00Z",
    "ownerId": "user-abc",
    "version": {
        "number": 3,
        "message": "Fixed typos",
        "createdAt": "2024-02-01T00:00:00Z",
        "authorId": "user-xyz",
    },
    "body": {
        "storage": {
            "value": "<p>Hello <strong>world</strong></p>",
            "representation": "storage",
        }
    },
    "labels": {"results": [{"name": "draft"}, {"name": "architecture"}]},
    "_links": {
        "webui": "/wiki/spaces/SPACE/pages/12345/Test+Page",
    },
}

_SAMPLE_USER: dict[str, Any] = {
    "accountId": "user-abc",
    "displayName": "Leo Simons",
}


def _enter(self: object) -> object:
    return self


def _make_mock_client() -> MagicMock:
    client = MagicMock(spec=ConfluenceClient)
    client.__enter__ = _enter
    client.__exit__ = MagicMock(return_value=False)
    client._base_url = "https://example.atlassian.net"
    client.get_page.return_value = _SAMPLE_PAGE
    client.get_user.return_value = _SAMPLE_USER
    client.list_page_attachments.return_value = []
    return client


def _make_config() -> MagicMock:
    config = MagicMock()
    config.url = "https://example.atlassian.net"
    config.username = "user@example.com"
    config.api_token = "test-token"
    return config


class TestExportPage:
    def test_export_page_by_id_writes_md(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.commands.confluence.load_config", return_value=mock_config),
            patch("mdd.commands.confluence.ConfluenceClient", return_value=mock_client),
        ):
            # --log-level=INFO so log.info("Exported: ...") routes to stderr
            result = _cli_main(
                [
                    "--log-level=INFO",
                    "confluence",
                    "export-page",
                    "12345",
                    "--output",
                    str(tmp_path),
                ]
            )

        assert result == 0
        err = capsys.readouterr().err
        assert "Exported" in err

        # Find the written file
        md_files = list(tmp_path.glob("*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text(encoding="utf-8")

        # Check frontmatter is present
        assert "---" in content
        assert "confluence:" in content
        assert "page_id:" in content
        assert "12345" in content

        # Check export header callout
        assert "**Confluence export**" in content

    def test_export_page_frontmatter_fields(self, tmp_path: Path) -> None:
        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.commands.confluence.load_config", return_value=mock_config),
            patch("mdd.commands.confluence.ConfluenceClient", return_value=mock_client),
        ):
            cmd_confluence(["export-page", "12345", "--output", str(tmp_path)])

        md_files = list(tmp_path.glob("*.md"))
        content = md_files[0].read_text(encoding="utf-8")

        assert "space_key:" in content
        assert "SPACE" in content
        assert "version:" in content
        assert "exported_at:" in content
        # title and source_format are no longer written to frontmatter (P03 phase 6)
        assert "title:" not in content
        assert "source_format:" not in content

    def test_export_page_body_content(self, tmp_path: Path) -> None:
        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.commands.confluence.load_config", return_value=mock_config),
            patch("mdd.commands.confluence.ConfluenceClient", return_value=mock_client),
        ):
            cmd_confluence(["export-page", "12345", "--output", str(tmp_path)])

        md_files = list(tmp_path.glob("*.md"))
        content = md_files[0].read_text(encoding="utf-8")
        assert "**world**" in content

    def test_export_page_config_error_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch(
            "mdd.commands.confluence.load_config",
            side_effect=ConfigError("No config found"),
        ):
            result = cmd_confluence(["export-page", "12345", "--output", str(tmp_path)])

        assert result == 1
        err = capsys.readouterr().err
        assert "config" in err.lower()

    def test_export_page_confluence_error_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_client = _make_mock_client()
        mock_client.get_page.side_effect = ConfluenceError("API failure")
        mock_config = _make_config()

        with (
            patch("mdd.commands.confluence.load_config", return_value=mock_config),
            patch("mdd.commands.confluence.ConfluenceClient", return_value=mock_client),
        ):
            result = cmd_confluence(["export-page", "12345", "--output", str(tmp_path)])

        assert result == 1
        err = capsys.readouterr().err
        assert "Confluence" in err or "API" in err


class TestNotImplementedSubcommands:
    def test_create_page_missing_file_returns_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = cmd_confluence(["create-page", "file.md"])
        assert result == 1
        err = capsys.readouterr().err
        assert "not found" in err or "Error" in err

    def test_update_page_missing_file_returns_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = cmd_confluence(["update-page", "nonexistent_file_xyz.md"])
        assert result == 1
        err = capsys.readouterr().err
        assert "not found" in err or "Error" in err


class TestDispatch:
    def test_no_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence([])
        assert exc_info.value.code == 2

    def test_unknown_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(["notacommand"])
        assert exc_info.value.code == 2

    def test_export_no_subsubcmd_exits(self) -> None:
        # Argparse rejects the legacy two-token form: `export` alone is not a
        # subcommand (the flat name is `export-page`).
        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(["export"])
        assert exc_info.value.code == 2

    def test_export_page_config_missing_value_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(["export-page", "12345", "--config"])
        assert exc_info.value.code == 2

    def test_export_page_output_missing_value_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(["export-page", "12345", "--output"])
        assert exc_info.value.code == 2


class TestConfluenceHelp:
    """`mdd confluence --help` lists each flat subcommand."""

    def test_help_mentions_each_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(["--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        for name in ("sync-space", "export-page", "create-page", "update-page", "whoami"):
            assert name in out
