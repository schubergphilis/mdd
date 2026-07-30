"""Tests for `mdd.confluence.export.export_page` console output.

The per-page `attachments synced` summary line is suppressed when nothing
was synced. The line should still appear when at least one attachment was
synced.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from mdd.confluence.attachments import AttachmentSyncSummary
from mdd.confluence.export import export_page

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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


def test_zero_attachments_suppresses_summary_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = _page_data()
    client = _fake_client()
    client.get_page.return_value = page
    with patch(
        "mdd.confluence.export.sync_all_attachments",
        return_value=([], AttachmentSyncSummary()),
    ):
        export_page(client, "42", tmp_path, page_data=page)

    captured = capsys.readouterr()
    assert "attachments synced" not in captured.out


def test_nonzero_attachments_emits_summary_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    page = _page_data()
    client = _fake_client()
    client.get_page.return_value = page
    summary = AttachmentSyncSummary(synced=2, converted=0, skipped=0, total_bytes=200 * 1024)
    with (
        patch(
            "mdd.confluence.export.sync_all_attachments",
            return_value=([], summary),
        ),
        caplog.at_level("INFO", logger="mdd.confluence.export"),
    ):
        export_page(client, "42", tmp_path, page_data=page)

    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "2 attachments synced" in msgs
    assert "0 converted" in msgs
    assert "0 skipped" in msgs
