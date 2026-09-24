"""Tests for mdd commands: confluence update page."""

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


def _write_local_image(md_path: Path) -> Path:
    """Create ``<stem>-attachments/diagram.png`` beside *md_path* and return it."""
    img = md_path.parent / f"{md_path.stem}-attachments" / "diagram.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\x89PNG fake bytes")
    return img


class TestUpdatePageDryRun:
    def test_dry_run_no_put_and_no_upload(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        _write_local_image(md_path)
        _write_md_file(md_path, fm, "## New heading\n\nChanged text.\n\n![d](diagram.png)")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            caplog.at_level("INFO", logger="mdd.confluence.attachments.update"),
        ):
            from mdd.confluence.update import update_page

            result = update_page(md_path, mock_config, dry_run=True, yes=True)

        assert result == 0
        mock_client.put_page.assert_not_called()
        mock_client.upload_attachment.assert_not_called()
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "would upload attachment diagram.png" in msgs

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


class TestUpdatePageDeclined:
    def test_declined_prompt_uploads_nothing(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        _write_local_image(md_path)
        _write_md_file(md_path, fm, "## Changed\n\nDifferent.\n\n![d](diagram.png)")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update._confirm_push", return_value=False),
        ):
            from mdd.confluence.update import update_page

            result = update_page(md_path, mock_config, yes=False)

        assert result == 0
        mock_client.put_page.assert_not_called()
        mock_client.upload_attachment.assert_not_called()

    def test_confirmed_prompt_uploads_after_confirmation(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        img = _write_local_image(md_path)
        _write_md_file(md_path, fm, "## Changed\n\nDifferent.\n\n![d](diagram.png)")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        def _confirm(*, yes: bool) -> bool:  # pyright: ignore[reportUnusedParameter]
            # Nothing may have been uploaded by the time the prompt shows.
            mock_client.upload_attachment.assert_not_called()
            return True

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update._confirm_push", side_effect=_confirm),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.update import update_page

            result = update_page(md_path, mock_config, yes=False)

        assert result == 0
        mock_client.upload_attachment.assert_called_once_with("12345", img)
        mock_client.put_page.assert_called_once()
        assert "diagram.png" in md_path.read_text()

    def test_attachment_only_change_uploads_without_new_version(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        img = _write_local_image(md_path)
        body = f"```{{=confluence}}\n{_STORAGE_XHTML}\n```\n\n![d](diagram.png)\n"
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

            result = update_page(md_path, mock_config, yes=True)

        assert result == 0
        mock_client.upload_attachment.assert_called_once_with("12345", img)
        mock_client.put_page.assert_not_called()
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "Only attachments changed" in msgs

    def test_attachment_only_change_records_manifest_and_keeps_version(
        self, tmp_path: Path
    ) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        _write_local_image(md_path)
        body = f"```{{=confluence}}\n{_STORAGE_XHTML}\n```\n\n![d](diagram.png)\n"
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
        from mdd.confluence.frontmatter import read as read_fm

        new_fm, new_body = read_fm(md_path)
        conf: dict[str, Any] = new_fm["confluence"]
        attachments: list[dict[str, Any]] = conf["attachments"]
        assert [a["filename"] for a in attachments] == ["diagram.png"]
        assert attachments[0]["version"] == 1
        assert attachments[0]["sha256"]
        before: dict[str, Any] = fm["confluence"]
        for key in ("version", "updated_at", "updated_by", "exported_at"):
            assert conf[key] == before[key]
        assert "![d](diagram.png)" in new_body

    def test_second_run_after_attachment_only_push_is_noop(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md_path = tmp_path / "My-Page.md"
        fm = _make_frontmatter(version=3)
        _write_local_image(md_path)
        body = f"```{{=confluence}}\n{_STORAGE_XHTML}\n```\n\n![d](diagram.png)\n"
        _write_md_file(md_path, fm, body)

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
            patch("mdd.confluence.update.insert_mdd_footer", return_value=_STORAGE_XHTML),
        ):
            from mdd.confluence.update import update_page

            assert update_page(md_path, mock_config, yes=True) == 0
            mock_client.upload_attachment.reset_mock()
            confirm = MagicMock(return_value=True)
            caplog.clear()
            with (
                patch("mdd.confluence.update._confirm_push", confirm),
                caplog.at_level("INFO", logger="mdd.confluence.update"),
            ):
                assert update_page(md_path, mock_config, yes=False) == 0

        mock_client.upload_attachment.assert_not_called()
        mock_client.put_page.assert_not_called()
        confirm.assert_not_called()
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "No changes detected" in msgs
        assert "Only attachments changed" not in msgs


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


def _is_locally_edited(md_path: Path) -> bool:
    from mdd.confluence.state import LocalPage
    from mdd.confluence.sync.local_edits import detect_local_edits
    from mdd.confluence.sync_diff import DesiredPage

    tracked = {
        "12345": LocalPage(
            path=md_path,
            page_id="12345",
            title="My Page",
            parent_id=None,
            status="current",
            version_number=3,
            space_key="SPACE",
            space_id="98306",
        )
    }
    desired = {
        "12345": DesiredPage(
            page_id="12345",
            title="My Page",
            parent_id=None,
            status="current",
            version_number=3,
            version_created_at="2024-02-01T00:00:00Z",
            space_id="98306",
        )
    }
    return bool(detect_local_edits(tracked, desired, md_path.parent))


class TestUpdatePageNoOpClearsLocalEdit:
    def _run(self, md_path: Path, *, dry_run: bool = False) -> MagicMock:
        mock_client = _make_mock_client()
        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
            patch("mdd.confluence.update.insert_mdd_footer", return_value=_STORAGE_XHTML),
        ):
            from mdd.confluence.update import update_page

            assert update_page(md_path, _make_config(), yes=True, dry_run=dry_run) == 0
        return mock_client

    def test_noop_push_is_no_longer_a_local_edit(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My-Page.md"
        _write_md_file(
            md_path, _make_frontmatter(version=3), f"```{{=confluence}}\n{_STORAGE_XHTML}\n```\n"
        )
        original = md_path.read_text()
        assert _is_locally_edited(md_path)

        mock_client = self._run(md_path)

        mock_client.put_page.assert_not_called()
        assert not _is_locally_edited(md_path)
        assert md_path.read_text() == original

    def test_dry_run_noop_leaves_mtime_alone(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My-Page.md"
        _write_md_file(
            md_path, _make_frontmatter(version=3), f"```{{=confluence}}\n{_STORAGE_XHTML}\n```\n"
        )

        self._run(md_path, dry_run=True)

        assert _is_locally_edited(md_path)

    def test_attachment_only_push_is_no_longer_a_local_edit(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My-Page.md"
        _write_local_image(md_path)
        body = f"```{{=confluence}}\n{_STORAGE_XHTML}\n```\n\n![d](diagram.png)\n"
        _write_md_file(md_path, _make_frontmatter(version=3), body)

        mock_client = self._run(md_path)

        mock_client.upload_attachment.assert_called_once()
        assert not _is_locally_edited(md_path)


def _page_with_storage(storage: str) -> dict[str, Any]:
    page = dict(_SAMPLE_PAGE)
    page["body"] = {"storage": {"value": storage, "representation": "storage"}}
    return page


class TestUpdatePageSoftBreaks:
    def test_moved_soft_breaks_in_paragraph_skip_put(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My-Page.md"
        _write_md_file(md_path, _make_frontmatter(version=3), "Hello *big\nworld*\nagain\n")

        mock_client = _make_mock_client()
        mock_client.get_page.return_value = _page_with_storage(
            "<p>Hello <em>big world</em> again</p>"
        )

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.update import update_page

            result = update_page(md_path, _make_config(), yes=True)

        assert result == 0
        mock_client.put_page.assert_not_called()

    def test_moved_line_break_in_code_block_puts(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My-Page.md"
        _write_md_file(md_path, _make_frontmatter(version=3), "```\na\nb c\n```\n")

        mock_client = _make_mock_client()
        mock_client.get_page.return_value = _page_with_storage("<pre><code>a b\nc</code></pre>")

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.update import update_page

            result = update_page(md_path, _make_config(), yes=True)

        assert result == 0
        mock_client.put_page.assert_called_once()


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


class TestNoResolveLinksFlag:
    def test_default_resolves_links(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        _write_md_file(md_path, _make_frontmatter(), "# P\n")
        with (
            patch("mdd.commands.confluence.update_page", return_value=0) as update,
            patch("mdd.commands.confluence.load_config", return_value=_make_config()),
        ):
            assert cmd_confluence(["update-page", str(md_path)]) == 0
        assert update.call_args.kwargs["resolve_links"] is True

    def test_flag_turns_resolution_off(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        _write_md_file(md_path, _make_frontmatter(), "# P\n")
        with (
            patch("mdd.commands.confluence.update_page", return_value=0) as update,
            patch("mdd.commands.confluence.load_config", return_value=_make_config()),
        ):
            assert cmd_confluence(["update-page", str(md_path), "--no-resolve-links"]) == 0
        assert update.call_args.kwargs["resolve_links"] is False
