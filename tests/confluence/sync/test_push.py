"""Tests for mdd.confluence.sync.push."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.config import ConfluenceConfig
from mdd.confluence.managed import ManagedConfig
from mdd.confluence.sync._types import SyncOptions, SyncSummary
from mdd.confluence.sync.events import make_managed_helpers
from mdd.confluence.sync.push import PushCtx, push_content
from mdd.confluence.sync_diff import EventKind, SyncEvent
from mdd.confluence.update import PushOutcome

if TYPE_CHECKING:
    from pathlib import Path


def _ctx(summary: SyncSummary) -> PushCtx:
    client = MagicMock(spec=ConfluenceClient)
    client.get_page.return_value = {"id": "1"}

    def _no_skip(_page_id: str, _page: dict[str, Any]) -> bool:
        return False

    return PushCtx(
        client=client,
        config=ConfluenceConfig(url="https://example.atlassian.net", username="u", api_token="t"),
        opts=SyncOptions(),
        summary=summary,
        get_managed_cfg=ManagedConfig,
        record_managed_skip=_no_skip,
    )


def _events(tmp_path: Path, count: int) -> list[SyncEvent]:
    return [
        SyncEvent(
            kind=EventKind.LOCAL_PUSH, page_id=str(i), current_path=str(tmp_path / f"p{i}.md")
        )
        for i in range(count)
    ]


def _run(tmp_path: Path, outcomes: list[PushOutcome]) -> SyncSummary:
    summary = SyncSummary()
    mirror = SimpleNamespace(tracked={})
    with patch("mdd.confluence.sync.push.update_page_outcome", side_effect=outcomes):
        push_content(_events(tmp_path, len(outcomes)), mirror, _ctx(summary))
    return summary


class TestPushContentCounting:
    def test_all_noop_pushes_count_zero(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("INFO", logger="mdd.confluence.sync.push"):
            summary = _run(tmp_path, [PushOutcome.NO_CHANGE, PushOutcome.NO_CHANGE])

        assert summary.content_pushed == 0
        assert summary.failures == []
        msgs = [r.getMessage() for r in caplog.records]
        assert not any(m.startswith("push: ") for m in msgs)
        assert "push skipped: p0.md (no-change)" in msgs

    def test_pushed_and_attachment_only_are_counted(self, tmp_path: Path) -> None:
        summary = _run(
            tmp_path,
            [PushOutcome.PUSHED, PushOutcome.ATTACHMENTS_ONLY, PushOutcome.NO_CHANGE],
        )

        assert summary.content_pushed == 2

    def test_failed_push_is_recorded_as_failure(self, tmp_path: Path) -> None:
        summary = _run(tmp_path, [PushOutcome.FAILED])

        assert summary.content_pushed == 0
        assert summary.failures == ["push 0: update_page failed"]


class TestPushOutcome:
    @pytest.mark.parametrize(
        ("outcome", "sent"),
        [
            (PushOutcome.PUSHED, True),
            (PushOutcome.ATTACHMENTS_ONLY, True),
            (PushOutcome.NO_CHANGE, False),
            (PushOutcome.NOT_PUSHED, False),
            (PushOutcome.FAILED, False),
        ],
    )
    def test_sent_changes(self, outcome: PushOutcome, sent: bool) -> None:
        assert outcome.sent_changes is sent


def _write_tracked(path: Path, page_id: str) -> None:
    fm = {
        "confluence": {
            "page_id": page_id,
            "space_key": "ENG",
            "space_id": "98306",
            "title": f"Page {page_id}",
            "version": 3,
        }
    }
    body = yaml.safe_dump(fm, sort_keys=False)
    path.write_text(f"---\n{body}---\n\nChanged body.\n", encoding="utf-8")


def _page(page_id: str, *, space_id: str, space_key: str) -> dict[str, Any]:
    return {
        "id": page_id,
        "title": f"Page {page_id}",
        "spaceId": space_id,
        "parentId": "1",
        "version": {"number": 3},
        "body": {"storage": {"value": "<p>old</p>"}},
        "_links": {"webui": f"/spaces/{space_key}/pages/{page_id}"},
    }


def _enter(self: object) -> object:
    return self


class TestPushRefusalsAreReportedPerPage:
    def test_foreign_space_page_fails_and_the_run_continues(self, tmp_path: Path) -> None:
        _write_tracked(tmp_path / "p0.md", "0")
        _write_tracked(tmp_path / "p1.md", "1")
        pages = {
            "0": _page("0", space_id="55555", space_key="HR"),
            "1": _page("1", space_id="98306", space_key="ENG"),
        }
        client = MagicMock(spec=ConfluenceClient)
        client.__enter__ = _enter
        client.__exit__ = MagicMock(return_value=False)
        client.get_page.side_effect = lambda page_id, **_kw: pages[page_id]  # pyright: ignore[reportUnknownLambdaType]
        client.put_page.return_value = {"version": {"number": 4}}
        summary = SyncSummary()
        ctx = _ctx(summary)
        ctx.client = client

        with (
            patch("mdd.confluence.update.ConfluenceClient", return_value=client),
            patch("mdd.confluence.update.get_mirror_url", return_value=None),
        ):
            push_content(_events(tmp_path, 2), SimpleNamespace(tracked={}), ctx)

        assert summary.failures == ["push 0: update_page failed"]
        assert summary.content_pushed == 1
        assert [c.args[0] for c in client.put_page.call_args_list] == ["1"]

    def test_managed_check_failure_is_a_page_failure(self, tmp_path: Path) -> None:
        summary = SyncSummary()
        ctx = _ctx(summary)
        client = MagicMock(spec=ConfluenceClient)
        client.get_page.return_value = _page("0", space_id="98306", space_key="ENG")
        client.get_page_ancestors.side_effect = ConfluenceError("HTTP 503")
        cfg = ManagedConfig.model_validate(
            {
                "external_publishers": [{"name": "pipe"}],
                "managed_subtrees": [
                    {"space_key": "ENG", "root_page_id": "999", "publisher_name": "pipe"}
                ],
            }
        )
        _get_cfg, record_skip = make_managed_helpers(
            client, SyncOptions(managed_config=cfg), summary
        )
        ctx.client = client
        ctx.record_managed_skip = record_skip

        with patch(
            "mdd.confluence.sync.push.update_page_outcome", return_value=PushOutcome.PUSHED
        ) as update:
            push_content(_events(tmp_path, 1), SimpleNamespace(tracked={}), ctx)

        update.assert_not_called()
        assert len(summary.failures) == 1
        assert summary.failures[0].startswith("push managed-check 0: could not fetch the ancestors")
