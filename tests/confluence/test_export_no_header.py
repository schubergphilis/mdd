"""Tests for the ``--no-header`` / ``include_export_header=False`` path.

The default ``mdd confluence export`` prepends a "Confluence export"
blockquote callout to the markdown body. ``--no-header`` suppresses
that callout — useful for round-trip experiments and other scripted
exports where the header is noise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from mdd.confluence.attachments import AttachmentSyncSummary
from mdd.confluence.export import export_page

if TYPE_CHECKING:
    from pathlib import Path


def _page_data(page_id: str = "999", title: str = "Sample") -> dict[str, Any]:
    return {
        "id": page_id,
        "title": title,
        "status": "current",
        "spaceId": "s1",
        "spaceKey": "ENG",
        "parentId": None,
        "body": {"storage": {"value": "<p>Hello world.</p>"}},
        "_links": {"webui": f"/wiki/spaces/ENG/pages/{page_id}/{title}"},
        "version": {"number": 1, "createdAt": "2026-05-12T00:00:00Z"},
    }


def _fake_client() -> MagicMock:
    client = MagicMock()
    client.base_url = "https://example.atlassian.net"
    client.get_user.return_value = {"displayName": "Bot"}
    return client


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_default_includes_export_header(tmp_path: Path) -> None:
    page = _page_data()
    client = _fake_client()
    client.get_page.return_value = page
    with patch(
        "mdd.confluence.export.sync_all_attachments",
        return_value=([], AttachmentSyncSummary()),
    ):
        out = export_page(client, "999", tmp_path, page_data=page)
    body = _read(out)
    assert "> **Confluence export**" in body
    assert "# Sample" in body


def test_no_header_suppresses_callout(tmp_path: Path) -> None:
    page = _page_data()
    client = _fake_client()
    client.get_page.return_value = page
    with patch(
        "mdd.confluence.export.sync_all_attachments",
        return_value=([], AttachmentSyncSummary()),
    ):
        out = export_page(
            client,
            "999",
            tmp_path,
            page_data=page,
            include_export_header=False,
        )
    body = _read(out)
    assert "**Confluence export**" not in body
    assert "# Sample" in body
    assert "Hello world." in body
    # And no stray blank-line preamble from a missing header.
    body_after_frontmatter = body.split("---\n", 2)[2].lstrip("\n")
    assert body_after_frontmatter.startswith("# Sample")
