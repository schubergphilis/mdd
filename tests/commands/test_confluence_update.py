"""Tests for mdd commands: confluence update page (spec 009c)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from mdd.cli import main as _cli_main
from mdd.confluence.client import ConfluenceClient
from mdd.confluence.config import ConfluenceConfig

if TYPE_CHECKING:
    from pathlib import Path


def cmd_confluence(args: list[str]) -> int:
    """Test helper: invoke mdd confluence via argparse."""
    return _cli_main(["confluence", *args])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STORAGE_XHTML = "<p>Hello <strong>world</strong></p>"

_SAMPLE_PAGE: dict[str, Any] = {
    "id": "12345",
    "title": "My Page",
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
            "value": _STORAGE_XHTML,
            "representation": "storage",
        }
    },
    "labels": {"results": []},
    "_links": {"webui": "/wiki/spaces/SPACE/pages/12345/My+Page"},
}

_SAMPLE_USER: dict[str, Any] = {
    "accountId": "user-xyz",
    "displayName": "Jane Doe",
}

_PUT_RESPONSE: dict[str, Any] = {
    "id": "12345",
    "title": "My Page",
    "version": {
        "number": 4,
        "message": "Updated via mdd",
        "createdAt": "2026-05-08T10:00:00Z",
        "authorId": "user-xyz",
    },
}


def _make_frontmatter(version: int = 3) -> dict[str, Any]:
    return {
        "confluence": {
            "url": "https://example.atlassian.net/wiki/spaces/SPACE/pages/12345",
            "page_id": "12345",
            "space_key": "SPACE",
            "space_id": "98306",
            "title": "My Page",
            "status": "current",
            "version": version,
            "version_message": "Fixed typos",
            "created_at": "2024-01-01T00:00:00Z",
            "created_by": {"account_id": "user-abc", "display_name": "Leo Simons"},
            "updated_at": "2024-02-01T00:00:00Z",
            "updated_by": {"account_id": "user-xyz", "display_name": "Jane Doe"},
            "labels": [],
            "exported_at": "2024-02-01T12:00:00Z",
            "source_format": "storage",
            "attachments": [],
        }
    }


def _write_md_file(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    fm_str = yaml.safe_dump(frontmatter, default_flow_style=False, sort_keys=False)
    content = f"---\n{fm_str}---\n\n{body}\n"
    path.write_text(content, encoding="utf-8")


def _enter(self: object) -> object:
    return self


def _make_mock_client() -> MagicMock:
    client = MagicMock(spec=ConfluenceClient)
    client.__enter__ = _enter
    client.__exit__ = MagicMock(return_value=False)
    client.base_url = "https://example.atlassian.net"
    client.get_page.return_value = _SAMPLE_PAGE
    client.get_user.return_value = _SAMPLE_USER
    client.upload_attachment.return_value = {"results": [{"version": {"number": 1}}]}
    client.put_page.return_value = _PUT_RESPONSE
    return client


def _make_config() -> ConfluenceConfig:
    return ConfluenceConfig(
        url="https://example.atlassian.net",
        username="user@example.com",
        api_token="test-token",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUpdatePageConflict:
    def test_remote_version_newer_returns_1(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md_path = tmp_path / "My-Page.md"
        # Local says version 2, but remote says version 3
        fm = _make_frontmatter(version=2)
        _write_md_file(md_path, fm, "## Content\n\nSome text.")

        mock_client = _make_mock_client()  # remote version is 3
        mock_config = _make_config()

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            caplog.at_level("ERROR", logger="mdd.confluence.update"),
        ):
            from mdd.confluence.update import update_page

            result = update_page(md_path, mock_config, yes=True)

        assert result == 1
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "Conflict" in msgs or "conflict" in msgs
        mock_client.put_page.assert_not_called()

    def test_conflict_message_contains_versions(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=1)
        _write_md_file(md_path, fm, "Content.")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            caplog.at_level("ERROR", logger="mdd.confluence.update"),
        ):
            from mdd.confluence.update import update_page

            update_page(md_path, mock_config, yes=True)

        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "3" in msgs  # remote version
        assert "1" in msgs  # local version


class TestUpdatePageDryRun:
    def test_dry_run_no_put(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        _write_md_file(md_path, fm, "## New heading\n\nChanged text.")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client):
            from mdd.confluence.update import update_page

            result = update_page(md_path, mock_config, dry_run=True, yes=True)

        assert result == 0
        mock_client.put_page.assert_not_called()

    def test_dry_run_no_frontmatter_rewrite(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        _write_md_file(md_path, fm, "## Changed\n\nDifferent content.")
        original_content = md_path.read_text()

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client):
            from mdd.confluence.update import update_page

            update_page(md_path, mock_config, dry_run=True, yes=True)

        assert md_path.read_text() == original_content


class TestUpdatePageYes:
    def test_yes_skips_prompt_and_calls_put(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        _write_md_file(md_path, fm, "## Changed\n\nDifferent content.")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.update import update_page

            result = update_page(md_path, mock_config, yes=True)

        assert result == 0
        mock_client.put_page.assert_called_once()

    def test_yes_rewrites_frontmatter(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        _write_md_file(md_path, fm, "## Changed\n\nDifferent content for update.")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.update import update_page

            update_page(md_path, mock_config, yes=True)

        # Version should be updated
        content = md_path.read_text()
        assert "version: 4" in content


class TestUpdatePageEmptyDiff:
    def test_no_changes_skips_put(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)

        # Write body that will render to same XHTML as remote after normalization
        # The remote has: <p>Hello <strong>world</strong></p>
        # We use the same storage content as the page body (via {=confluence})
        body = f"```{{=confluence}}\n{_STORAGE_XHTML}\n```\n"
        _write_md_file(md_path, fm, body)

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
            patch("mdd.confluence.update.insert_mdd_footer", return_value=_STORAGE_XHTML),
        ):
            from mdd.confluence.update import update_page

            result = update_page(md_path, mock_config, yes=True)

        assert result == 0
        mock_client.put_page.assert_not_called()

    def test_no_changes_prints_message(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        body = f"```{{=confluence}}\n{_STORAGE_XHTML}\n```\n"
        _write_md_file(md_path, fm, body)

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
            patch("mdd.confluence.update.insert_mdd_footer", return_value=_STORAGE_XHTML),
            caplog.at_level("INFO", logger="mdd.confluence.update"),
        ):
            from mdd.confluence.update import update_page

            update_page(md_path, mock_config, yes=True)

        msgs = " ".join(r.getMessage() for r in caplog.records).lower()
        assert "no changes" in msgs or "empty" in msgs


class TestUpdatePageValidation:
    def test_missing_page_id_returns_1(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md_path = tmp_path / "Page.md"
        fm: dict[str, Any] = {"confluence": {"version": 1, "title": "Page"}}
        _write_md_file(md_path, fm, "Content.")

        from mdd.confluence.update import update_page

        with caplog.at_level("ERROR", logger="mdd.confluence.update"):
            result = update_page(md_path, _make_config(), yes=True)
        assert result == 1
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "page_id" in msgs

    def test_missing_version_returns_1(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md_path = tmp_path / "Page.md"
        fm: dict[str, Any] = {"confluence": {"page_id": "123", "title": "Page"}}
        _write_md_file(md_path, fm, "Content.")

        from mdd.confluence.update import update_page

        with caplog.at_level("ERROR", logger="mdd.confluence.update"):
            result = update_page(md_path, _make_config(), yes=True)
        assert result == 1
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "version" in msgs

    def test_file_not_found_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        md_path = tmp_path / "missing.md"

        from mdd.confluence.update import update_page

        result = update_page(md_path, _make_config(), yes=True)
        assert result == 1


class TestUpdatePageNonTTY:
    def test_non_tty_without_yes_returns_1(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        _write_md_file(md_path, fm, "## Changed\n\nDifferent content for tty test.")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
            patch("mdd.confluence.update.sys.stdin") as mock_stdin,
            caplog.at_level("ERROR", logger="mdd.confluence.update"),
        ):
            mock_stdin.isatty.return_value = False
            from mdd.confluence.update import update_page

            result = update_page(md_path, mock_config, yes=False)

        assert result == 1
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "--yes" in msgs or "non-interactive" in msgs


class TestUpdatePageCLI:
    def test_cli_update_page_missing_file(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = cmd_confluence(["update-page", "definitely_not_there.md"])
        assert result == 1
        err = capsys.readouterr().err
        assert "not found" in err or "Error" in err

    def test_cli_update_page_dry_run_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        _write_md_file(md_path, fm, "## Changed\n\nSome content.")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.commands.confluence.load_config", return_value=mock_config),
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
        ):
            result = cmd_confluence(["update-page", str(md_path), "--dry-run", "--yes"])

        assert result == 0
        mock_client.put_page.assert_not_called()

    def test_cli_update_page_no_args_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(["update-page"])
        assert exc_info.value.code == 2


class TestUpdatePage409Conflict:
    """PUT returning 409 must produce the friendly version-conflict message."""

    def test_409_from_put_returns_1_with_friendly_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mdd.confluence.client import ConfluenceError
        from mdd.confluence.update import update_page

        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        _write_md_file(md_path, fm, "## Changed\n\nDifferent content to trigger a diff.")

        mock_client = _make_mock_client()
        mock_client.put_page.side_effect = ConfluenceError(
            "PUT /wiki/api/v2/pages/12345 failed with 409: version conflict"
        )

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
        ):
            result = update_page(md_path, _make_config(), yes=True)

        assert result == 1
        err = capsys.readouterr().err
        # Must mention "Conflict" and the guidance to re-export
        assert "Conflict" in err or "conflict" in err
        assert "re-export" in err.lower() or "Re-export" in err
