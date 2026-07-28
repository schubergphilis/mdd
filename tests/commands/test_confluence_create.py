"""Tests for mdd commands: confluence create page (spec 009d)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from mdd.cli import main as _cli_main
from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.config import ConfluenceConfig

if TYPE_CHECKING:
    from pathlib import Path


def cmd_confluence(args: list[str]) -> int:
    """Test helper: invoke mdd confluence via argparse."""
    return _cli_main(["confluence", *args])


# ---------------------------------------------------------------------------
# Fixtures / shared helpers
# ---------------------------------------------------------------------------

_STUB_PAGE: dict[str, Any] = {
    "id": "99001",
    "title": "New Page (creating…)",
    "status": "current",
    "spaceId": "55000",
    "parentId": None,
    "createdAt": "2026-05-08T10:00:00Z",
    "ownerId": "user-creator",
    "version": {
        "number": 1,
        "message": "",
        "createdAt": "2026-05-08T10:00:00Z",
        "authorId": "user-creator",
    },
    "_links": {
        "webui": "/wiki/spaces/SCRATCH/pages/99001/New+Page",
    },
}

_FINAL_PAGE: dict[str, Any] = {
    "id": "99001",
    "title": "New Page",
    "status": "current",
    "spaceId": "55000",
    "parentId": None,
    "createdAt": "2026-05-08T10:00:00Z",
    "ownerId": "user-creator",
    "version": {
        "number": 2,
        "message": "Created via mdd",
        "createdAt": "2026-05-08T10:01:00Z",
        "authorId": "user-creator",
    },
    "_links": {
        "webui": "/wiki/spaces/SCRATCH/pages/99001/New+Page",
    },
}

_SPACE_DATA: dict[str, Any] = {
    "id": "55000",
    "key": "SCRATCH",
    "name": "Scratch Space",
}

_USER_DATA: dict[str, Any] = {
    "accountId": "user-creator",
    "displayName": "Leo Simons",
}


def _make_config() -> ConfluenceConfig:
    return ConfluenceConfig(
        url="https://example.atlassian.net",
        username="user@example.com",
        api_token="test-token",
    )


def _enter(self: object) -> object:
    return self


def _make_mock_client() -> MagicMock:
    client = MagicMock(spec=ConfluenceClient)
    client.__enter__ = _enter
    client.__exit__ = MagicMock(return_value=False)
    client.base_url = "https://example.atlassian.net"
    client.get_space.return_value = _SPACE_DATA
    client.post_page.return_value = _STUB_PAGE
    client.put_page.return_value = _FINAL_PAGE
    client.get_user.return_value = _USER_DATA
    client.upload_attachment.return_value = {"results": [{"version": {"number": 1}}]}
    return client


def _write_md(path: Path, frontmatter: dict[str, Any] | None, body: str) -> None:
    if frontmatter is not None:
        fm_str = yaml.safe_dump(frontmatter, default_flow_style=False, sort_keys=False)
        content = f"---\n{fm_str}---\n\n{body}\n"
    else:
        content = body
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Net-new file: happy path
# ---------------------------------------------------------------------------


class TestCreatePageHappyPath:
    def test_calls_post_and_put(self, tmp_path: Path) -> None:
        md_path = tmp_path / "new-page.md"
        _write_md(md_path, {"confluence": {"space_key": "SCRATCH"}}, "# New Page\n\nHello.")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            result = create_page(md_path, mock_config, space_key="SCRATCH")

        assert result == 0
        mock_client.get_space.assert_called_once_with("SCRATCH")
        mock_client.post_page.assert_called_once()
        mock_client.put_page.assert_called_once()

    def test_post_stub_uses_creating_marker(self, tmp_path: Path) -> None:
        md_path = tmp_path / "new-page.md"
        _write_md(md_path, None, "# My Great Page\n\nContent.")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, mock_config, space_key="SCRATCH")

        call_kwargs = mock_client.post_page.call_args.kwargs
        assert "(creating…)" in call_kwargs["title"]

    def test_put_uses_final_title(self, tmp_path: Path) -> None:
        md_path = tmp_path / "new-page.md"
        _write_md(md_path, None, "# My Great Page\n\nContent.")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, mock_config, space_key="SCRATCH")

        put_args = mock_client.put_page.call_args
        # put_page(page_id, title, body_xhtml, version=2, message=...)
        assert put_args.args[1] == "My Great Page"
        assert put_args.kwargs["version"] == 2

    def test_frontmatter_rewritten_with_page_id(self, tmp_path: Path) -> None:
        md_path = tmp_path / "new-page.md"
        _write_md(md_path, None, "# New Page\n\nHello.")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, mock_config, space_key="SCRATCH")

        content = md_path.read_text()
        assert "page_id" in content
        assert "99001" in content

    def test_frontmatter_rewritten_with_full_metadata(self, tmp_path: Path) -> None:
        md_path = tmp_path / "new-page.md"
        _write_md(md_path, None, "# New Page\n\nHello.")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, mock_config, space_key="SCRATCH")

        content = md_path.read_text()
        for field in ("space_key", "space_id", "version", "exported_at", "status"):
            assert field in content, f"Expected {field!r} in rewritten frontmatter"

    def test_returns_0_on_success(self, tmp_path: Path) -> None:
        md_path = tmp_path / "new-page.md"
        _write_md(md_path, None, "# New Page\n\nContent.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            result = create_page(md_path, _make_config(), space_key="SCRATCH")

        assert result == 0

    def test_prints_created_url(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        md_path = tmp_path / "new-page.md"
        _write_md(md_path, None, "# New Page\n\nContent.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
            caplog.at_level("INFO", logger="mdd.confluence.create"),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, _make_config(), space_key="SCRATCH")

        assert any("Created:" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Idempotency guard
# ---------------------------------------------------------------------------


class TestIdempotencyGuard:
    def test_file_with_page_id_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        md_path = tmp_path / "existing.md"
        fm: dict[str, Any] = {
            "confluence": {
                "page_id": "12345",
                "space_key": "SCRATCH",
                "title": "Existing Page",
                "version": 3,
            }
        }
        _write_md(md_path, fm, "# Existing Page\n\nContent.")

        mock_client = _make_mock_client()
        mock_config = _make_config()

        with patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client):
            from mdd.confluence.create import create_page

            result = create_page(md_path, mock_config, space_key="SCRATCH")

        assert result == 1
        mock_client.post_page.assert_not_called()
        mock_client.put_page.assert_not_called()

    def test_file_with_page_id_prints_helpful_message(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md_path = tmp_path / "existing.md"
        fm: dict[str, Any] = {
            "confluence": {
                "page_id": "12345",
                "space_key": "SCRATCH",
                "version": 1,
            }
        }
        _write_md(md_path, fm, "Content.")

        with (
            patch("mdd.confluence.create.ConfluenceClient"),
            caplog.at_level("ERROR", logger="mdd.confluence.create"),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, _make_config(), space_key="SCRATCH")

        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "update page" in msgs.lower() or "update" in msgs.lower()
        assert "page_id" in msgs


# ---------------------------------------------------------------------------
# Title resolution precedence
# ---------------------------------------------------------------------------


class TestTitleResolution:
    def test_arg_takes_precedence_over_frontmatter(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        fm: dict[str, Any] = {"confluence": {"space_key": "SCRATCH", "title": "FM Title"}}
        _write_md(md_path, fm, "# H1 Title\n\nContent.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, _make_config(), space_key="SCRATCH", title="Arg Title")

        put_args = mock_client.put_page.call_args
        assert put_args.args[1] == "Arg Title"

    def test_h1_used_when_frontmatter_has_stale_title(self, tmp_path: Path) -> None:
        # confluence.title is no longer consulted — H1 from body is used instead.
        md_path = tmp_path / "page.md"
        fm: dict[str, Any] = {"confluence": {"space_key": "SCRATCH", "title": "FM Title"}}
        _write_md(md_path, fm, "# H1 Title\n\nContent.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, _make_config(), space_key="SCRATCH")

        put_args = mock_client.put_page.call_args
        assert put_args.args[1] == "H1 Title"

    def test_h1_used_when_no_arg_or_frontmatter_title(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        fm: dict[str, Any] = {"confluence": {"space_key": "SCRATCH"}}
        _write_md(md_path, fm, "# H1 Title\n\nContent.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, _make_config(), space_key="SCRATCH")

        put_args = mock_client.put_page.call_args
        assert put_args.args[1] == "H1 Title"

    def test_filename_stem_used_when_no_h1(self, tmp_path: Path) -> None:
        # When no --title and no H1, create_page falls back to filename stem.
        md_path = tmp_path / "my-page.md"
        fm: dict[str, Any] = {"confluence": {"space_key": "SCRATCH"}}
        _write_md(md_path, fm, "No heading here, just prose.\n\nMore content.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            result = create_page(md_path, _make_config(), space_key="SCRATCH")

        assert result == 0
        put_args = mock_client.put_page.call_args
        assert put_args.args[1] == "my-page"

    def test_filename_stem_used_when_no_frontmatter_and_no_h1(self, tmp_path: Path) -> None:
        # No frontmatter, no H1 — filename stem is the title fallback.
        md_path = tmp_path / "my-page.md"
        _write_md(md_path, None, "Just prose, no heading.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            result = create_page(md_path, _make_config(), space_key="SCRATCH")

        assert result == 0
        put_args = mock_client.put_page.call_args
        assert put_args.args[1] == "my-page"


# ---------------------------------------------------------------------------
# Space key resolution
# ---------------------------------------------------------------------------


class TestSpaceKeyResolution:
    def test_arg_space_key_used(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# Page Title\n\nContent.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, _make_config(), space_key="SCRATCH")

        mock_client.get_space.assert_called_once_with("SCRATCH")

    def test_frontmatter_space_key_used_when_no_arg(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        fm: dict[str, Any] = {"confluence": {"space_key": "MYSPACE"}}
        _write_md(md_path, fm, "# Page Title\n\nContent.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, _make_config())

        mock_client.get_space.assert_called_once_with("MYSPACE")

    def test_missing_space_key_returns_1(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# Page Title\n\nContent.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            caplog.at_level("ERROR", logger="mdd.confluence.create"),
        ):
            from mdd.confluence.create import create_page

            result = create_page(md_path, _make_config())

        assert result == 1
        mock_client.post_page.assert_not_called()
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "space" in msgs.lower()


# ---------------------------------------------------------------------------
# Parent resolution
# ---------------------------------------------------------------------------


class TestParentResolution:
    def test_numeric_parent_id(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# Page Title\n\nContent.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, _make_config(), space_key="SCRATCH", parent="77777")

        call_kwargs = mock_client.post_page.call_args.kwargs
        assert call_kwargs["parent_id"] == "77777"

    def test_url_parent(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# Page Title\n\nContent.")

        mock_client = _make_mock_client()
        parent_url = "https://example.atlassian.net/wiki/spaces/SCRATCH/pages/77777/Parent"

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, _make_config(), space_key="SCRATCH", parent=parent_url)

        call_kwargs = mock_client.post_page.call_args.kwargs
        assert call_kwargs["parent_id"] == "77777"

    def test_frontmatter_parent_id(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        fm: dict[str, Any] = {"confluence": {"space_key": "SCRATCH", "parent_id": "88888"}}
        _write_md(md_path, fm, "# Page Title\n\nContent.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, _make_config())

        call_kwargs = mock_client.post_page.call_args.kwargs
        assert call_kwargs["parent_id"] == "88888"

    def test_no_parent_creates_at_root(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# Page Title\n\nContent.")

        mock_client = _make_mock_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, _make_config(), space_key="SCRATCH")

        call_kwargs = mock_client.post_page.call_args.kwargs
        assert call_kwargs["parent_id"] is None


# ---------------------------------------------------------------------------
# API error handling
# ---------------------------------------------------------------------------


class TestAPIErrors:
    def test_post_failure_returns_1(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# Page Title\n\nContent.")

        mock_client = _make_mock_client()
        mock_client.post_page.side_effect = ConfluenceError("POST 403: Forbidden")

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            caplog.at_level("ERROR", logger="mdd.confluence.create"),
        ):
            from mdd.confluence.create import create_page

            result = create_page(md_path, _make_config(), space_key="SCRATCH")

        assert result == 1
        assert any(r.levelname == "ERROR" for r in caplog.records)

    def test_put_failure_returns_1_and_writes_partial_frontmatter(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# Page Title\n\nContent.")

        mock_client = _make_mock_client()
        mock_client.put_page.side_effect = ConfluenceError("PUT 503: Service Unavailable")

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            result = create_page(md_path, _make_config(), space_key="SCRATCH")

        assert result == 1
        # Partial frontmatter should be written so update page can recover
        content = md_path.read_text()
        assert "page_id" in content
        assert "99001" in content

    def test_get_space_failure_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# Page Title\n\nContent.")

        mock_client = _make_mock_client()
        mock_client.get_space.side_effect = ConfluenceError("Space not found: BADKEY")

        with patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client):
            from mdd.confluence.create import create_page

            result = create_page(md_path, _make_config(), space_key="BADKEY")

        assert result == 1
        mock_client.post_page.assert_not_called()


# ---------------------------------------------------------------------------
# Export header stripping
# ---------------------------------------------------------------------------


class TestExportHeaderStripping:
    def test_export_header_stripped_before_render(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        body = "> **Confluence export**\n>\n> This page was exported.\n\n# Real Content\n\nHello."
        _write_md(md_path, None, body)

        mock_client = _make_mock_client()
        captured_body: list[str] = []

        def capture_put(  # pyright: ignore[reportAny]
            page_id: str, title: str, body_xhtml: str, version: int, message: str = ""
        ) -> dict[str, Any]:
            captured_body.append(body_xhtml)
            return _FINAL_PAGE

        mock_client.put_page.side_effect = capture_put

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            from mdd.confluence.create import create_page

            create_page(md_path, _make_config(), space_key="SCRATCH", title="Real Content")

        assert captured_body, "put_page was not called"
        assert "Confluence export" not in captured_body[0]


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCreatePageCLI:
    def test_cli_create_page_no_args_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(["create-page"])
        assert exc_info.value.code == 2

    def test_cli_create_page_missing_file_returns_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_confluence(["create-page", "nonexistent.md"])
        assert result == 1
        err = capsys.readouterr().err
        assert "not found" in err or "Error" in err

    def test_cli_create_page_calls_create_page(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# Hello World\n\nContent.")

        mock_config = _make_config()
        mock_client = _make_mock_client()

        with (
            patch("mdd.commands.confluence.load_config", return_value=mock_config),
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            result = cmd_confluence(["create-page", str(md_path), "--space", "SCRATCH"])

        assert result == 0
        mock_client.post_page.assert_called_once()
        mock_client.put_page.assert_called_once()

    def test_cli_passes_parent_flag(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# Hello\n\nContent.")

        mock_config = _make_config()
        mock_client = _make_mock_client()

        with (
            patch("mdd.commands.confluence.load_config", return_value=mock_config),
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            cmd_confluence(["create-page", str(md_path), "--space", "SCRATCH", "--parent", "77777"])

        call_kwargs = mock_client.post_page.call_args.kwargs
        assert call_kwargs["parent_id"] == "77777"

    def test_cli_passes_title_flag(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# H1\n\nContent.")

        mock_config = _make_config()
        mock_client = _make_mock_client()

        with (
            patch("mdd.commands.confluence.load_config", return_value=mock_config),
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            cmd_confluence(
                ["create-page", str(md_path), "--space", "SCRATCH", "--title", "Override"]
            )

        put_args = mock_client.put_page.call_args
        assert put_args.args[1] == "Override"

    def test_cli_passes_message_flag(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# Page\n\nContent.")

        mock_config = _make_config()
        mock_client = _make_mock_client()

        with (
            patch("mdd.commands.confluence.load_config", return_value=mock_config),
            patch("mdd.confluence.create.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            cmd_confluence(
                [
                    "create-page",
                    str(md_path),
                    "--space",
                    "SCRATCH",
                    "--message",
                    "Initial import",
                ]
            )

        put_args = mock_client.put_page.call_args
        assert put_args.kwargs.get("message") == "Initial import"

    def test_cli_unknown_option_exits(self, tmp_path: Path) -> None:
        md_path = tmp_path / "page.md"
        _write_md(md_path, None, "# Page\n\nContent.")

        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(["create-page", str(md_path), "--unknown-flag"])
        assert exc_info.value.code == 2

    def test_cli_create_no_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(["create"])
        assert exc_info.value.code == 2
