"""Tests for mdd.confluence.create — stub-page recovery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest

from mdd.confluence.create import (
    _extract_page_meta,  # pyright: ignore[reportPrivateUsage]
    create_page,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.url = "https://example.atlassian.net"
    cfg.username = "user@example.com"
    cfg.api_token = "tok"
    return cfg


def _stub_page_response(page_id: str = "42") -> dict[str, Any]:
    return {
        "id": page_id,
        "title": "My Page (creating…)",
        "status": "current",
        "spaceId": "SPACE1",
        "_links": {"webui": f"/wiki/spaces/TEST/pages/{page_id}"},
    }


def _final_page_response(page_id: str = "42") -> dict[str, Any]:
    return {
        "id": page_id,
        "title": "My Page",
        "status": "current",
        "spaceId": "SPACE1",
        "createdAt": "2024-01-01T00:00:00Z",
        "ownerId": "uid1",
        "version": {"number": 2, "authorId": "uid1", "createdAt": "2024-01-01T00:00:00Z"},
        "_links": {"webui": f"/wiki/spaces/TEST/pages/{page_id}"},
    }


def _make_client(
    *,
    stub_response: dict[str, Any] | None = None,
    final_response: dict[str, Any] | None = None,
    attachment_sync_raises: Exception | None = None,
    put_raises: Exception | None = None,
) -> MagicMock:
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)

    client.get_space.return_value = {"id": "SPACE1"}
    client.post_page.return_value = stub_response or _stub_page_response()
    client.get_user.return_value = {"displayName": "Alice"}
    client.upload_attachment.return_value = {"results": [{"version": {"number": 1}}]}

    if attachment_sync_raises is not None:
        client.upload_attachment.side_effect = attachment_sync_raises

    if put_raises is not None:
        client.put_page.side_effect = put_raises
    else:
        client.put_page.return_value = final_response or _final_page_response()

    return client


def _md_with_body(tmp_path: Path, body: str = "# My Page\n\nContent here.\n") -> Path:
    md = tmp_path / "page.md"
    md.write_text(body, encoding="utf-8")
    return md


def _read_conf_block(md: Path) -> dict[str, Any]:
    """Read and return the 'confluence' dict from a markdown file's frontmatter."""
    import yaml

    content = md.read_text(encoding="utf-8")
    fm_block = content[4 : content.find("\n---\n", 4)]
    parsed: Any = yaml.safe_load(fm_block)  # pyright: ignore[reportAny]
    assert isinstance(parsed, dict)
    fm: dict[str, Any] = cast("dict[str, Any]", parsed)
    conf_raw: Any = fm.get("confluence")  # pyright: ignore[reportAny]
    assert isinstance(conf_raw, dict)
    return cast("dict[str, Any]", conf_raw)


class TestCreatePageRecovery:
    """Partial failures after stub creation must persist page_id."""

    def test_attachment_sync_failure_writes_page_id_to_frontmatter(self, tmp_path: Path) -> None:
        """If attachment sync fails, frontmatter must already contain page_id."""
        md = _md_with_body(tmp_path)

        # Simulate attachment sync raising (via upload_attachment.side_effect).
        # We do this by patching sync_attachments_for_update directly.
        config = _make_config()
        client = _make_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=client),
            patch(
                "mdd.confluence.create.sync_attachments_for_update",
                side_effect=OSError("disk full"),
            ),
        ):
            rc = create_page(md, config, space_key="TEST", title="My Page")

        assert rc == 1

        # Frontmatter must now have page_id so update page can resume.
        conf = _read_conf_block(md)
        assert conf.get("page_id") == "42"

    def test_md_conversion_failure_writes_page_id_to_frontmatter(self, tmp_path: Path) -> None:
        """If markdown conversion fails, frontmatter must already contain page_id."""
        md = _md_with_body(tmp_path)

        config = _make_config()
        client = _make_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=client),
            patch(
                "mdd.confluence.create.render_confluence_storage",
                side_effect=ValueError("conversion error"),
            ),
        ):
            rc = create_page(md, config, space_key="TEST", title="My Page")

        assert rc == 1

        conf = _read_conf_block(md)
        assert conf.get("page_id") == "42"

    def test_partial_frontmatter_includes_url(self, tmp_path: Path) -> None:
        """Partial frontmatter must include url so update can link without extra GET."""
        md = _md_with_body(tmp_path)

        config = _make_config()
        client = _make_client()

        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=client),
            patch(
                "mdd.confluence.create.sync_attachments_for_update",
                side_effect=OSError("disk full"),
            ),
        ):
            rc = create_page(md, config, space_key="TEST", title="My Page")

        assert rc == 1

        conf = _read_conf_block(md)
        assert "url" in conf
        assert conf["url"]  # must be non-empty

    def test_successful_create_writes_full_frontmatter(self, tmp_path: Path) -> None:
        """Happy path: full frontmatter is written after successful PUT."""
        md = _md_with_body(tmp_path)

        config = _make_config()
        client = _make_client()

        with patch("mdd.confluence.create.ConfluenceClient", return_value=client):
            rc = create_page(md, config, space_key="TEST", title="My Page")

        assert rc == 0

        conf = _read_conf_block(md)
        # Full frontmatter should include all fields
        assert conf.get("page_id") == "42"
        assert conf.get("version") == 2
        assert conf.get("space_key") == "TEST"


class TestPartialFrontmatterCompleteness:
    """Partial frontmatter must include url and attachments."""

    def test_put_failure_partial_frontmatter_includes_attachments(self, tmp_path: Path) -> None:
        """When PUT fails after attachment sync, manifest must be in frontmatter."""
        img = tmp_path / "diagram.png"
        img.write_bytes(b"PNG data")

        md = tmp_path / "page.md"
        md.write_text("# My Page\n\n![diagram](diagram.png)\n", encoding="utf-8")

        config = _make_config()
        from mdd.confluence.client import ConfluenceError

        client = _make_client(put_raises=ConfluenceError("500 server error"))

        with patch("mdd.confluence.create.ConfluenceClient", return_value=client):
            rc = create_page(md, config, space_key="TEST", title="My Page")

        assert rc == 1

        conf = _read_conf_block(md)
        # url must be present
        assert conf.get("url")
        # attachments list must not be empty (we uploaded diagram.png to the stub)
        atts_raw: Any = conf.get("attachments")  # pyright: ignore[reportAny]
        assert isinstance(atts_raw, list)
        atts: list[dict[str, Any]] = cast("list[dict[str, Any]]", atts_raw)
        assert len(atts) >= 1
        filenames = [a.get("filename") for a in atts]
        assert "diagram.png" in filenames


class TestExtractPageMeta:
    """Unit tests for the page-metadata coercion helper."""

    def test_returns_safe_defaults_for_empty_page(self) -> None:
        meta = _extract_page_meta({}, exported_at="2026-05-21T00:00:00Z")
        assert meta == {
            "page_id": "",
            "title": "",
            "status": "current",
            "space_id": "",
            "parent_id": None,
            "version_num": 1,
            "version_author_id": None,
            "version_created_at": "2026-05-21T00:00:00Z",
            "webui_url": "",
        }

    def test_extracts_all_fields_when_present(self) -> None:
        page: dict[str, Any] = {
            "id": "1234",
            "title": "Hello",
            "status": "archived",
            "spaceId": "SPACE",
            "parentId": "5678",
            "version": {
                "number": 3,
                "authorId": "user-1",
                "createdAt": "2026-04-01T10:00:00Z",
            },
            "_links": {"webui": "/wiki/page/1234"},
        }
        meta = _extract_page_meta(page, exported_at="2026-05-21T00:00:00Z")
        assert meta["page_id"] == "1234"
        assert meta["title"] == "Hello"
        assert meta["status"] == "archived"
        assert meta["space_id"] == "SPACE"
        assert meta["parent_id"] == "5678"
        assert meta["version_num"] == 3
        assert meta["version_author_id"] == "user-1"
        assert meta["version_created_at"] == "2026-04-01T10:00:00Z"
        assert meta["webui_url"] == "/wiki/page/1234"

    def test_falls_back_to_exported_at_when_version_missing_created_at(self) -> None:
        page: dict[str, Any] = {"version": {"number": 2}}
        meta = _extract_page_meta(page, exported_at="2026-05-21T00:00:00Z")
        assert meta["version_num"] == 2
        assert meta["version_author_id"] is None
        assert meta["version_created_at"] == "2026-05-21T00:00:00Z"

    def test_non_dict_version_and_links_raise(self) -> None:
        # API-response models propagate ValidationError outward —
        # an unexpected shape is a real bug, not a silent fallback case.
        from pydantic import ValidationError

        page: dict[str, Any] = {"version": "not a dict", "_links": ["nope"]}
        with pytest.raises(ValidationError):
            _ = _extract_page_meta(page, exported_at="ts")

    def test_treats_empty_string_author_id_as_none(self) -> None:
        page: dict[str, Any] = {"version": {"authorId": ""}}
        meta = _extract_page_meta(page, exported_at="ts")
        assert meta["version_author_id"] is None
