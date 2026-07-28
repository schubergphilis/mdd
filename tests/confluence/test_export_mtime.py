"""Regression test: a freshly exported page must not look locally edited.

`export_page` records `exported_at` in frontmatter at second precision,
while the file system stamps the .md with sub-second mtime. The sync
local-edit heuristic in :mod:`mdd.confluence.sync.local_edits` compares
``mtime > exported_at`` and would otherwise flag every page right after
export as a `LOCAL_PUSH`, which produced "277 local pushes" on a fresh
sync of a 277-page space.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from mdd.confluence.attachments import AttachmentSyncSummary
from mdd.confluence.export import export_page
from mdd.confluence.frontmatter import read as read_frontmatter
from mdd.confluence.state import LocalPage
from mdd.confluence.sync.local_edits import detect_local_edits
from mdd.confluence.sync_diff import DesiredPage

if TYPE_CHECKING:
    from pathlib import Path


def _page_data() -> dict[str, Any]:
    return {
        "id": "42",
        "title": "Sample",
        "status": "current",
        "spaceId": "s1",
        "spaceKey": "ENG",
        "parentId": None,
        "body": {"storage": {"value": "<p>Hello world.</p>"}},
        "_links": {"webui": "/wiki/spaces/ENG/pages/42/Sample"},
        "version": {"number": 7, "createdAt": "2026-05-12T00:00:00Z"},
    }


def _fake_client() -> MagicMock:
    client = MagicMock()
    client.base_url = "https://example.atlassian.net"
    client.get_user.return_value = {"displayName": "Bot"}
    return client


def test_fresh_export_is_not_locally_edited(tmp_path: Path) -> None:
    page = _page_data()
    client = _fake_client()
    client.get_page.return_value = page
    with patch(
        "mdd.confluence.export.sync_all_attachments",
        return_value=([], AttachmentSyncSummary()),
    ):
        out = export_page(client, "42", tmp_path, page_data=page)

    fm, _ = read_frontmatter(out)
    conf = fm["confluence"]
    exported_at = conf["exported_at"]
    mtime = out.stat().st_mtime
    assert mtime <= datetime.fromisoformat(exported_at).timestamp(), (
        f"mtime ({mtime}) must not be newer than exported_at ({exported_at})"
    )

    tracked = {
        "42": LocalPage(
            path=out,
            page_id="42",
            title="Sample",
            parent_id=None,
            status="CURRENT",
            version_number=7,
            space_key="ENG",
            space_id="s1",
            attachments_manifest=[],
        )
    }
    desired = {
        "42": DesiredPage(
            page_id="42",
            title="Sample",
            parent_id=None,
            status="current",
            version_number=7,
            version_created_at="2026-05-12T00:00:00Z",
            space_id="s1",
        )
    }
    assert detect_local_edits(tracked, desired, tmp_path) == set()
