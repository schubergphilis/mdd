"""How each caller of the managed check handles a check that could not run."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.export import (
    _apply_managed_classification,  # pyright: ignore[reportPrivateUsage]
    _ExportContext,  # pyright: ignore[reportPrivateUsage]
)
from mdd.confluence.managed import ManagedConfig
from mdd.confluence.publish_office import _PublishAction  # pyright: ignore[reportPrivateUsage]
from mdd.confluence.sync._types import SyncSummary
from mdd.confluence.sync.office_publish import (
    _record_office_managed_skip,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _subtree_config() -> ManagedConfig:
    return ManagedConfig.model_validate(
        {
            "external_publishers": [{"name": "pipe"}],
            "managed_subtrees": [
                {"space_key": "ENG", "root_page_id": "999", "publisher_name": "pipe"}
            ],
        }
    )


def _page() -> dict[str, Any]:  # pyright: ignore[reportExplicitAny]
    return {
        "id": "42",
        "title": "Page",
        "spaceId": "98306",
        "parentId": "7",
        "version": {"number": 2},
        "_links": {"webui": "/spaces/ENG/pages/42/Page"},
    }


def _failing_client() -> MagicMock:
    client = MagicMock(spec=ConfluenceClient)
    client.get_page_ancestors.side_effect = ConfluenceError("HTTP 503")
    return client


def test_sync_office_publish_skips_and_records_failure() -> None:
    summary = SyncSummary()
    skipped = _record_office_managed_skip(
        "42", _page(), "", _failing_client(), _subtree_config(), summary
    )
    assert skipped is True
    assert len(summary.failures) == 1
    assert summary.failures[0].startswith("office-publish managed-check 42:")


def test_publish_office_stops_and_records_failure(tmp_path: Path) -> None:
    action = _PublishAction(
        client=_failing_client(),
        page_id="42",
        md_path=tmp_path / "p.md",
        body_xhtml="",
        managed_config=_subtree_config(),
        _page_data=_page(),
    )
    assert action._is_managed_elsewhere() is True  # pyright: ignore[reportPrivateUsage]
    assert action.summary.failures[0].startswith("managed-check 42:")


def test_export_falls_back_to_payload_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ctx = _ExportContext(
        client=_failing_client(),
        page_id="42",
        out_dir=tmp_path,
        page_data=_page(),
        max_attachment_size_bytes=None,
        existing_attachments_manifest=None,
        managed_config=_subtree_config(),
        include_export_header=True,
        skip_attachments=False,
    )
    conf_fm: dict[str, Any] = {}  # pyright: ignore[reportExplicitAny]
    with caplog.at_level("WARNING", logger="mdd.confluence.export"):
        result = _apply_managed_classification(ctx, conf_fm, "")
    assert result is not None
    assert not result.is_managed
    assert "classifying from the page payload alone" in caplog.text
    assert "managed_by" not in conf_fm
