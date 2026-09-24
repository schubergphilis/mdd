"""A page that fails to export during pull is recorded, not fatal.

Both pull entry points (``create_remote_pages`` for new remote pages and
``pull_content`` for content edits) must confine any exception raised while
exporting one page to that page, record it on the summary and carry on with
the next page, mirroring what the push side already does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mdd.confluence.managed import ManagedConfig
from mdd.confluence.sync._types import SyncOptions, SyncSummary
from mdd.confluence.sync.pull import PullCtx, create_remote_pages, pull_content
from mdd.confluence.sync_diff import DesiredPage, EventKind, SyncEvent

if TYPE_CHECKING:
    from pathlib import Path


def _desired(page_id: str) -> DesiredPage:
    return DesiredPage(
        page_id=page_id,
        title=f"Page {page_id}",
        parent_id=None,
        status="current",
        version_number=2,
        version_created_at="2026-01-01T00:00:00Z",
        space_id="s1",
    )


def _ctx(tmp_path: Path, client: MagicMock | None = None) -> PullCtx:
    return PullCtx(
        client=client if client is not None else MagicMock(),
        page_to_outdir={},
        output_dir=tmp_path,
        opts=SyncOptions(),
        summary=SyncSummary(),
        get_managed_cfg=ManagedConfig,
    )


def _deep_blockquote_body(depth: int) -> str:
    return "<blockquote>" * depth + "<p>x</p>" + "</blockquote>" * depth


def _resolve_under(tmp_path: Path) -> Any:
    def _resolve(_mirror: Any, _page_id: str, current_path: str) -> Path:
        return tmp_path / current_path

    return _resolve


def _remote_page(page_id: str) -> dict[str, Any]:
    body = _deep_blockquote_body(200) if page_id == "1" else "<p>ok</p>"
    return {
        "id": page_id,
        "title": f"Page {page_id}",
        "status": "current",
        "spaceId": "s1",
        "spaceKey": "ENG",
        "parentId": None,
        "body": {"storage": {"value": body}},
        "_links": {"webui": f"/wiki/spaces/ENG/pages/{page_id}"},
        "version": {"number": 2, "createdAt": "2026-01-01T00:00:00Z"},
    }


def _export_side_effect(failing_id: str, exc: BaseException) -> Any:
    def _export(_client: Any, page_id: str, out_dir: Path, **_kwargs: Any) -> Path:
        if page_id == failing_id:
            raise exc
        out_dir.mkdir(parents=True, exist_ok=True)
        written = out_dir / f"page-{page_id}.md"
        written.write_text("# ok\n")
        return written

    return _export


@pytest.mark.parametrize(
    "exc", [RecursionError("maximum recursion depth exceeded"), ValueError("bad body")]
)
def test_new_page_export_failure_is_recorded_and_next_page_still_syncs(
    tmp_path: Path, exc: BaseException
) -> None:
    ctx = _ctx(tmp_path)
    events = [
        SyncEvent(kind=EventKind.NEW, page_id="1", desired=_desired("1")),
        SyncEvent(kind=EventKind.NEW, page_id="2", desired=_desired("2")),
    ]
    with patch("mdd.confluence.sync.pull.export_page", side_effect=_export_side_effect("1", exc)):
        create_remote_pages(events, ctx)

    assert ctx.summary.new_from_confluence == 1
    assert ctx.summary.failures == [f"new 1: {exc}"]
    assert (tmp_path / "page-2.md").exists()


@pytest.mark.parametrize(
    "exc", [RecursionError("maximum recursion depth exceeded"), ValueError("bad body")]
)
def test_content_pull_failure_is_recorded_and_next_page_still_syncs(
    tmp_path: Path, exc: BaseException
) -> None:
    ctx = _ctx(tmp_path)
    mirror = MagicMock()
    mirror.tracked = {}
    events = [
        SyncEvent(
            kind=EventKind.CONTENT_EDIT, page_id="1", desired=_desired("1"), current_path="a.md"
        ),
        SyncEvent(
            kind=EventKind.CONTENT_EDIT, page_id="2", desired=_desired("2"), current_path="b.md"
        ),
    ]
    with (
        patch("mdd.confluence.sync.pull.export_page", side_effect=_export_side_effect("1", exc)),
        patch(
            "mdd.confluence.sync.pull.resolve_path_after_rename",
            side_effect=_resolve_under(tmp_path),
        ),
    ):
        pull_content(events, mirror, ctx)

    assert ctx.summary.content_pulled == 1
    assert ctx.summary.failures == [f"pull 1: {exc}"]
    assert (tmp_path / "page-2.md").exists()


def test_content_pull_of_deeply_nested_body_goes_through_the_real_exporter(tmp_path: Path) -> None:
    """End-to-end through ``export_page``: a body nested 200 blockquotes deep
    is exported (the reader bounds nesting instead of recursing) and the
    following page is pulled as usual."""
    client = MagicMock()
    client.base_url = "https://example.atlassian.net"
    client.get_user.return_value = {"displayName": "Bot"}
    client.get_page.side_effect = _remote_page
    ctx = _ctx(tmp_path, client)
    mirror = MagicMock()
    mirror.tracked = {}
    events = [
        SyncEvent(
            kind=EventKind.CONTENT_EDIT, page_id="1", desired=_desired("1"), current_path="a.md"
        ),
        SyncEvent(
            kind=EventKind.CONTENT_EDIT, page_id="2", desired=_desired("2"), current_path="b.md"
        ),
    ]
    with (
        patch(
            "mdd.confluence.sync.pull.resolve_path_after_rename",
            side_effect=_resolve_under(tmp_path),
        ),
        patch("mdd.confluence.export.sync_all_attachments", return_value=([], MagicMock(synced=0))),
        patch("mdd.confluence.export.check_confluence"),
    ):
        pull_content(events, mirror, ctx)

    assert ctx.summary.failures == []
    assert ctx.summary.content_pulled == 2
    assert (tmp_path / "Page 1.md").exists()
    assert (tmp_path / "Page 2.md").exists()
