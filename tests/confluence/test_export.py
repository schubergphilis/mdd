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
from mdd.confluence.sync.deletions import (
    _delete_path_fs,  # pyright: ignore[reportPrivateUsage]
)

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


def _attachment_client(filename: str, data: bytes) -> MagicMock:
    """Client whose every page carries one attachment *filename* with *data*."""
    client = _fake_client()
    att = {
        "title": filename,
        "version": {"number": 1},
        "_links": {"download": f"/wiki/download/attachments/x/{filename}"},
    }
    client.list_page_attachments.return_value = [att]

    def download_to_file(_att: dict[str, Any], dest: Path) -> int:
        dest.write_bytes(data)
        return len(data)

    client.download_attachment_to_file.side_effect = download_to_file
    return client


def test_sibling_pages_with_same_sanitized_title_get_separate_attachment_dirs(
    tmp_path: Path,
) -> None:
    """``X`` and ``X.`` sanitize to the same stem; the second page's attachments
    dir follows its disambiguated ``.md`` name instead of sharing the first's."""
    first = _page_data() | {"id": "1", "title": "X"}
    second = _page_data() | {"id": "2", "title": "X."}
    client = _attachment_client("a.png", b"png")

    first_path = export_page(client, "1", tmp_path, page_data=first)
    second_path = export_page(client, "2", tmp_path, page_data=second)

    assert first_path == tmp_path / "X.md"
    assert second_path == tmp_path / "X(2).md"
    assert (tmp_path / "X-attachments" / "a.png").exists()
    assert (tmp_path / "X(2)-attachments" / "a.png").exists()

    _delete_path_fs(second_path)

    assert not second_path.exists()
    assert not (tmp_path / "X(2)-attachments").exists()
    assert (tmp_path / "X-attachments" / "a.png").exists()
    assert first_path.exists()


def test_reexport_of_same_page_keeps_its_attachment_dir(tmp_path: Path) -> None:
    """An incremental re-export of a page reuses its own ``.md`` and attachments dir."""
    page = _page_data() | {"id": "1", "title": "X"}
    client = _attachment_client("a.png", b"png")

    export_page(client, "1", tmp_path, page_data=page)
    out_path = export_page(client, "1", tmp_path, page_data=page)

    assert out_path == tmp_path / "X.md"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["X-attachments", "X.md"]
