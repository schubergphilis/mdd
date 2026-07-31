"""Tests for the managed-elsewhere skip recording built by make_managed_helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from mdd.confluence.managed import ManagedConfig
from mdd.confluence.sync._types import SyncOptions, SyncSummary
from mdd.confluence.sync.events import make_managed_helpers

_PAGE_DATA: dict[str, Any] = {
    "id": "111",
    "spaceKey": "ENG",
    "version": {"authorId": "human-456"},
    "body": {"storage": {"value": "<p>hello</p>"}},
}


def _opts(config: ManagedConfig) -> SyncOptions:
    return SyncOptions(managed_config=config)


class TestRecordManagedSkip:
    def test_restriction_api_error_pushes_and_counts_unverified(self) -> None:
        """A restriction-check API error doesn't skip the page, but the summary counts it."""
        client = MagicMock()
        client.get_current_user.return_value = {"accountId": "my-account-id"}
        client.get_page_restrictions.side_effect = Exception("network error")

        summary = SyncSummary()
        config = ManagedConfig()
        _get_cfg, record_managed_skip = make_managed_helpers(client, _opts(config), summary)

        skipped = record_managed_skip("111", _PAGE_DATA)

        assert skipped is False  # fails open: sync proceeds to push
        assert summary.restriction_check_unverified == 1
        assert summary.managed_skips == {}

    def test_confirmed_unrestricted_page_not_counted(self) -> None:
        """A genuinely unrestricted page pushes with no unverified count."""
        client = MagicMock()
        client.get_current_user.return_value = {"accountId": "my-account-id"}
        client.get_page_restrictions.return_value = {
            "update": {
                "restrictions": {
                    "user": {"results": []},
                    "group": {"results": []},
                }
            }
        }

        summary = SyncSummary()
        config = ManagedConfig()
        _get_cfg, record_managed_skip = make_managed_helpers(client, _opts(config), summary)

        skipped = record_managed_skip("111", _PAGE_DATA)

        assert skipped is False
        assert summary.restriction_check_unverified == 0

    def test_confirmed_restricted_page_is_skipped_not_unverified(self) -> None:
        """A genuinely restricted page is skipped and recorded as a managed skip, not unverified."""
        client = MagicMock()
        client.get_current_user.return_value = {"accountId": "my-account-id"}
        client.get_page_restrictions.return_value = {
            "update": {
                "restrictions": {
                    "user": {"results": [{"accountId": "someone-else"}]},
                    "group": {"results": []},
                }
            }
        }

        summary = SyncSummary()
        config = ManagedConfig()
        _get_cfg, record_managed_skip = make_managed_helpers(client, _opts(config), summary)

        skipped = record_managed_skip("111", _PAGE_DATA)

        assert skipped is True
        assert summary.restriction_check_unverified == 0
        assert summary.managed_skips == {"_read_only": 1}
