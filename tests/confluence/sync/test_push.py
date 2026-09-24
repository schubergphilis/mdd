"""Tests for mdd.confluence.sync.push."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mdd.confluence.client import ConfluenceClient
from mdd.confluence.config import ConfluenceConfig
from mdd.confluence.managed import ManagedConfig
from mdd.confluence.sync._types import SyncOptions, SyncSummary
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
