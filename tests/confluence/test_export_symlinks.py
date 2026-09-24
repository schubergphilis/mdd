"""export_page refuses a symlinked directory anywhere between the mirror root and out_dir."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mdd.confluence.attachments import AttachmentSyncSummary
from mdd.confluence.export import export_page
from mdd.confluence.sync._types import SyncOptions, SyncSummary
from mdd.confluence.sync.pull import PullCtx, create_remote_pages
from mdd.confluence.sync_diff import DesiredPage, EventKind, SyncEvent
from mdd.utils.safe_write import SymlinkRefusedError

if TYPE_CHECKING:
    from pathlib import Path


def _plant_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks not supported on this platform")


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
    client.get_page.return_value = _page_data()
    return client


class TestExportPageRootChain:
    def test_symlinked_title_directory_refused_with_root(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        _plant_symlink(mirror / "Parent", outside)

        with (
            patch(
                "mdd.confluence.export.sync_all_attachments",
                return_value=([], AttachmentSyncSummary()),
            ),
            pytest.raises(SymlinkRefusedError),
        ):
            export_page(
                _fake_client(),
                "42",
                mirror / "Parent" / "Child",
                page_data=_page_data(),
                root=mirror,
            )

        assert list(outside.iterdir()) == []

    def test_real_title_directory_chain_is_created(self, tmp_path: Path) -> None:
        mirror = tmp_path / "mirror"
        mirror.mkdir()

        with patch(
            "mdd.confluence.export.sync_all_attachments",
            return_value=([], AttachmentSyncSummary()),
        ):
            out = export_page(
                _fake_client(),
                "42",
                mirror / "Parent" / "Child",
                page_data=_page_data(),
                root=mirror,
            )

        assert out == mirror / "Parent" / "Child" / "Sample.md"
        assert out.is_file()


class TestPullPassesMirrorRoot:
    def test_create_remote_pages_passes_output_dir_as_root(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "mirror"
        output_dir.mkdir()
        desired = DesiredPage(
            page_id="42",
            title="Sample",
            parent_id=None,
            status="current",
            version_number=1,
            version_created_at="2026-05-12T00:00:00Z",
            space_id="s1",
        )
        event = SyncEvent(kind=EventKind.NEW, page_id="42", desired=desired)
        ctx = PullCtx(
            client=MagicMock(),
            page_to_outdir={"42": output_dir / "Parent"},
            output_dir=output_dir,
            opts=SyncOptions(),
            summary=SyncSummary(),
            get_managed_cfg=MagicMock(),
        )

        with patch("mdd.confluence.sync.pull.export_page") as fake_export:
            fake_export.return_value = output_dir / "Parent" / "Sample.md"
            create_remote_pages([event], ctx)

        fake_export.assert_called_once()
        assert fake_export.call_args.args[2] == output_dir / "Parent"
        assert fake_export.call_args.kwargs["root"] == output_dir
