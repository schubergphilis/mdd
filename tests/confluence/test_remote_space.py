"""Tests for reading a page's space from the Confluence page payload."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.remote_space import (
    RemotePage,
    describe_remote_page,
    remote_space_key,
    space_key_from_payload,
    space_mismatch,
)


def _payload(**extra: Any) -> dict[str, Any]:  # pyright: ignore[reportExplicitAny]
    page: dict[str, Any] = {"id": "66011", "title": "Page", "spaceId": "131077"}  # pyright: ignore[reportExplicitAny]
    page.update(extra)
    return page


class TestSpaceKeyFromPayload:
    @pytest.mark.parametrize(
        ("webui", "expected"),
        [
            ("/spaces/MDDTEST/pages/66011/Page", "MDDTEST"),
            ("/wiki/spaces/~5570/pages/66011/Page", "~5570"),
            ("/spaces/%7E5570/pages/66011/Page", "~5570"),
            ("/pages/66011", ""),
            ("/spaces/", ""),
            ("", ""),
        ],
    )
    def test_webui_shapes(self, webui: str, expected: str) -> None:
        assert space_key_from_payload(_payload(_links={"webui": webui})) == expected

    def test_space_key_field_wins(self) -> None:
        page = _payload(spaceKey="ENG", _links={"webui": "/spaces/OTHER/pages/1"})
        assert space_key_from_payload(page) == "ENG"

    def test_malformed_links_are_ignored(self) -> None:
        assert space_key_from_payload(_payload(_links="nope")) == ""


class TestRemoteSpaceKey:
    def test_payload_key_needs_no_call(self) -> None:
        client = MagicMock(spec=ConfluenceClient)
        page = _payload(_links={"webui": "/spaces/ENG/pages/1"})
        assert remote_space_key(client, page) == "ENG"
        client.get_space_by_id.assert_not_called()

    def test_looks_up_space_id(self) -> None:
        client = MagicMock(spec=ConfluenceClient)
        client.get_space_by_id.return_value = {"id": "131077", "key": "MDDTEST"}
        assert remote_space_key(client, _payload()) == "MDDTEST"
        client.get_space_by_id.assert_called_once_with("131077")

    def test_no_space_id_is_empty(self) -> None:
        client = MagicMock(spec=ConfluenceClient)
        assert remote_space_key(client, {"id": "1"}) == ""
        client.get_space_by_id.assert_not_called()

    def test_invalid_space_id_raises_without_request(self) -> None:
        client = ConfluenceClient("https://example.atlassian.net", "u", lambda: "t")
        with (
            patch.object(client, "_request") as request,
            pytest.raises(ConfluenceError, match="space_id"),
        ):
            remote_space_key(client, _payload(spaceId="1/../../x"))
        request.assert_not_called()


class TestDescribeRemotePage:
    def test_fields_from_payload(self) -> None:
        client = MagicMock(spec=ConfluenceClient)
        remote = describe_remote_page(client, _payload(_links={"webui": "/spaces/ENG/pages/1"}))
        assert remote == RemotePage(
            page_id="66011", title="Page", space_id="131077", space_key="ENG"
        )
        assert remote.space_label == "ENG"

    def test_failed_lookup_is_unknown_and_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        client = MagicMock(spec=ConfluenceClient)
        client.get_space_by_id.side_effect = ConfluenceError("HTTP 404")
        with caplog.at_level("WARNING", logger="mdd.confluence.remote_space"):
            remote = describe_remote_page(client, _payload())
        assert remote.space_key == ""
        assert remote.space_label == "unknown"
        assert "could not look up the space of page 66011" in caplog.text


def _remote(space_id: str = "131077", space_key: str = "ENG") -> RemotePage:
    return RemotePage(page_id="66011", title="Page", space_id=space_id, space_key=space_key)


class TestSpaceMismatch:
    def test_same_space(self) -> None:
        assert space_mismatch(_remote(), local_space_key="ENG", local_space_id="131077") == ""

    def test_key_case_is_ignored(self) -> None:
        assert space_mismatch(_remote(), local_space_key="eng", local_space_id="") == ""

    def test_id_differs(self) -> None:
        msg = space_mismatch(_remote(), local_space_key="", local_space_id="999")
        assert "page 66011 is in space ENG (id 131077)" in msg
        assert "frontmatter says space unknown (id 999)" in msg

    def test_key_differs(self) -> None:
        msg = space_mismatch(_remote(space_key="HR"), local_space_key="ENG", local_space_id="")
        assert "space HR (id 131077)" in msg
        assert "frontmatter says space ENG." in msg

    def test_nothing_to_compare(self) -> None:
        assert space_mismatch(_remote(), local_space_key="", local_space_id="") == ""
        unknown = _remote(space_id="", space_key="")
        assert space_mismatch(unknown, local_space_key="ENG", local_space_id="1") == ""

    def test_matching_ids_win_over_a_changed_key(self) -> None:
        # A space key can be changed on Confluence; the id still names the space.
        assert space_mismatch(_remote(), local_space_key="OLDKEY", local_space_id="131077") == ""

    def test_ids_decide_even_when_keys_agree(self) -> None:
        msg = space_mismatch(_remote(), local_space_key="ENG", local_space_id="999")
        assert "frontmatter says space ENG (id 999)" in msg

    def test_surrounding_whitespace_is_ignored(self) -> None:
        assert space_mismatch(_remote(), local_space_key=" ENG ", local_space_id="") == ""
        assert space_mismatch(_remote(), local_space_key="", local_space_id=" 131077 ") == ""

    def test_control_characters_in_space_keys_are_neutralised(self) -> None:
        msg = space_mismatch(
            _remote(space_key="H\x1b[2KR"), local_space_key="EN\x9bG", local_space_id=""
        )
        assert "\x1b" not in msg
        assert "\x9b" not in msg
        assert "space H\ufffd[2KR" in msg
        assert "frontmatter says space EN\ufffdG" in msg

    def test_line_breaks_in_space_keys_are_neutralised(self) -> None:
        msg = space_mismatch(
            _remote(space_key="HR\nin space ENG"), local_space_key="ENG", local_space_id=""
        )
        assert "\n" not in msg
        assert "space HR\ufffdin space ENG (id 131077) on Confluence" in msg
