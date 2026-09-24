"""The cross-space probe only requests ids that are safe to put in a path."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from mdd.confluence.client import ConfluenceError
from mdd.confluence.sync.state import probe_cross_space

if TYPE_CHECKING:
    import pytest


def _client(page_space_id: Any = "999", space_key: str = "OTHER") -> MagicMock:  # pyright: ignore[reportExplicitAny]
    def _get(path: str, **_kw: Any) -> dict[str, Any]:  # pyright: ignore[reportExplicitAny]
        if path.startswith("/wiki/api/v2/pages/"):
            return {"spaceId": page_space_id}
        return {"key": space_key}

    client = MagicMock()
    client.get.side_effect = _get
    return client


def _requested_paths(client: MagicMock) -> list[str]:
    return [str(c.args[0]) for c in client.get.call_args_list]  # pyright: ignore[reportAny]


class TestProbeCrossSpace:
    def test_page_in_other_space_is_reported_with_key(self) -> None:
        client = _client()
        assert probe_cross_space(client, ["123"], "111") == ({"123"}, {"123": "OTHER"})
        assert _requested_paths(client) == ["/wiki/api/v2/pages/123", "/wiki/api/v2/spaces/999"]

    def test_page_in_same_space_is_not_reported(self) -> None:
        assert probe_cross_space(_client(page_space_id="111"), ["123"], "111") == (set(), {})

    def test_missing_page_is_not_reported(self) -> None:
        client = MagicMock()
        client.get.side_effect = ConfluenceError("404")
        assert probe_cross_space(client, ["123"], "111") == (set(), {})

    def test_space_lookup_failure_falls_back_to_space_id(self) -> None:
        client = MagicMock()
        client.get.side_effect = [{"spaceId": "999"}, ConfluenceError("403")]
        assert probe_cross_space(client, ["123"], "111") == ({"123"}, {"123": "999"})

    def test_non_alphanumeric_page_id_makes_no_request(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = _client()
        with caplog.at_level(logging.WARNING, logger="mdd.confluence.sync.state"):
            result = probe_cross_space(
                client, ["1/../../../rest/api/user/current?x=", "12.3", ""], "111"
            )
        assert result == (set(), {})
        client.get.assert_not_called()
        assert "cross-space check skipped" in caplog.text

    def test_invalid_id_does_not_stop_later_ids(self) -> None:
        client = _client()
        assert probe_cross_space(client, ["../x", "123"], "111") == ({"123"}, {"123": "OTHER"})

    def test_non_alphanumeric_space_id_is_not_requested(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = _client(page_space_id="9/../admin")
        with caplog.at_level(logging.WARNING, logger="mdd.confluence.sync.state"):
            result = probe_cross_space(client, ["123"], "111")
        assert result == (set(), {})
        assert _requested_paths(client) == ["/wiki/api/v2/pages/123"]
        assert "spaceId" in caplog.text
