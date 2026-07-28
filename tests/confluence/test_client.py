"""Tests for ConfluenceClient methods beyond retry behaviour."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from mdd.confluence.client import (
    ConfluenceClient,
    ConfluenceError,
    PutPageOptions,
    assert_relative_api_path,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_client() -> ConfluenceClient:
    return ConfluenceClient(
        base_url="https://example.atlassian.net",
        username="user@example.com",
        token_resolver=lambda: "test-token",
    )


def _mock_response(status_code: int, body: dict[str, Any] | None = None) -> MagicMock:
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.is_success = 200 <= status_code < 300
    mock.text = ""
    mock.content = b"{}"
    mock.json.return_value = body or {}
    return mock


class TestBaseUrl:
    def test_base_url_strips_trailing_slash(self) -> None:
        c = ConfluenceClient("https://x.net/", "u", lambda: "t")
        assert c.base_url == "https://x.net"

    def test_base_url_preserved(self) -> None:
        c = _make_client()
        assert c.base_url == "https://example.atlassian.net"


class TestGetSpace:
    def test_empty_results_raises(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"results": []})
        with (
            patch.object(httpx.Client, "request", return_value=resp),
            pytest.raises(ConfluenceError, match="Space not found"),
        ):
            client.get_space("MISSING")

    def test_malformed_result_raises(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"results": ["not-a-dict"]})
        with (
            patch.object(httpx.Client, "request", return_value=resp),
            pytest.raises(ConfluenceError, match="Unexpected"),
        ):
            client.get_space("BAD")

    def test_valid_space_returned(self) -> None:
        client = _make_client()
        space = {"id": "42", "key": "ENG", "name": "Engineering"}
        resp = _mock_response(200, {"results": [space]})
        with patch.object(httpx.Client, "request", return_value=resp):
            result = client.get_space("ENG")
        assert result["key"] == "ENG"


class TestGetPageAncestors:
    def test_returns_results_top_to_bottom(self) -> None:
        client = _make_client()
        ancestors = [
            {"id": "100", "title": "Root", "parentId": None, "spaceId": "98306"},
            {"id": "200", "title": "Middle", "parentId": "100", "spaceId": "98306"},
            {"id": "300", "title": "Direct Parent", "parentId": "200", "spaceId": "98306"},
        ]
        resp = _mock_response(200, {"results": ancestors})
        with patch.object(httpx.Client, "request", return_value=resp) as req:
            result = client.get_page_ancestors("400")
        assert len(result) == 3
        assert result[0]["title"] == "Root"
        assert result[-1]["title"] == "Direct Parent"
        # Hits the v2 ancestors endpoint
        assert "/wiki/api/v2/pages/400/ancestors" in req.call_args[0][1]

    def test_empty_results(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"results": []})
        with patch.object(httpx.Client, "request", return_value=resp):
            result = client.get_page_ancestors("42")
        assert result == []

    def test_non_list_results_returns_empty(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"results": "garbage"})
        with patch.object(httpx.Client, "request", return_value=resp):
            result = client.get_page_ancestors("42")
        assert result == []

    def test_invalid_page_id_rejected(self) -> None:
        client = _make_client()
        with pytest.raises(ConfluenceError, match="not a valid"):
            client.get_page_ancestors("../../admin")


class TestGetUser:
    def test_fetches_and_caches(self) -> None:
        client = _make_client()
        user = {"accountId": "abc", "displayName": "Alice"}
        resp = _mock_response(200, user)
        with patch.object(httpx.Client, "request", return_value=resp) as mock_req:
            r1 = client.get_user("abc")
            r2 = client.get_user("abc")  # cache hit
        assert r1["displayName"] == "Alice"
        assert r2["displayName"] == "Alice"
        assert mock_req.call_count == 1  # only one real request


class TestGetNonDictJson:
    def test_get_list_json_raises(self) -> None:
        client = _make_client()
        mock = MagicMock(spec=httpx.Response)
        mock.status_code = 200
        mock.is_success = True
        mock.json.return_value = ["list", "not", "dict"]
        with (
            patch.object(httpx.Client, "request", return_value=mock),
            pytest.raises(ConfluenceError, match="Expected JSON object"),
        ):
            client.get("/some/path")


class TestHead:
    def test_head_returns_response(self) -> None:
        client = _make_client()
        mock = MagicMock(spec=httpx.Response)
        mock.status_code = 200
        mock.is_success = True
        with patch.object(httpx.Client, "request", return_value=mock) as req:
            resp = client.head("/some/path")
        assert resp is mock
        req.assert_called_once()
        assert req.call_args[0][0] == "HEAD"


class TestGetFolder:
    def test_get_folder_calls_correct_endpoint(self) -> None:
        client = _make_client()
        folder = {"id": "f1", "title": "My Folder", "type": "folder"}
        resp = _mock_response(200, folder)
        with patch.object(httpx.Client, "request", return_value=resp) as req:
            result = client.get_folder("f1")
        assert result["id"] == "f1"
        assert "/wiki/api/v2/folders/f1" in req.call_args[0][1]


class TestPostPage:
    def test_creates_page(self) -> None:
        client = _make_client()
        created = {"id": "99", "version": {"number": 1}, "title": "New Page"}
        resp = _mock_response(200, created)
        with patch.object(httpx.Client, "request", return_value=resp):
            result = client.post_page(
                space_id="space1",
                parent_id=None,
                title="New Page",
                body="<p>hello</p>",
            )
        assert result["id"] == "99"

    def test_with_parent_id(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"id": "100"})
        with patch.object(httpx.Client, "request", return_value=resp) as req:
            client.post_page(space_id="s1", parent_id="parent42", title="Child", body="")
        payload = req.call_args[1]["json"]
        assert payload["parentId"] == "parent42"


class TestPutPage:
    def test_updates_page(self) -> None:
        client = _make_client()
        updated = {"id": "42", "version": {"number": 2}}
        resp = _mock_response(200, updated)
        with patch.object(httpx.Client, "request", return_value=resp):
            result = client.put_page("42", "Updated Title", "<p>new body</p>", version=2)
        assert result["id"] == "42"

    def test_sends_correct_payload(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"id": "42"})
        with patch.object(httpx.Client, "request", return_value=resp) as req:
            client.put_page("42", "My Title", "<p>body</p>", version=3, message="edit note")
        payload = req.call_args[1]["json"]
        assert payload["version"]["number"] == 3
        assert payload["version"]["message"] == "edit note"
        assert payload["title"] == "My Title"

    def test_default_status_is_current_and_no_parent_id(self) -> None:
        # S27 Phase 1: signature gained ``options=`` but defaults preserve
        # the original behaviour — no ``parentId`` in the body, status
        # remains ``"current"``.
        client = _make_client()
        resp = _mock_response(200, {"id": "42"})
        with patch.object(httpx.Client, "request", return_value=resp) as req:
            client.put_page("42", "T", "<p/>", version=2)
        payload = req.call_args[1]["json"]
        assert payload["status"] == "current"
        assert "parentId" not in payload

    def test_options_parent_id_sets_parentid(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"id": "42"})
        with patch.object(httpx.Client, "request", return_value=resp) as req:
            client.put_page(
                "42",
                "T",
                "<p/>",
                version=2,
                options=PutPageOptions(parent_id="500"),
            )
        payload = req.call_args[1]["json"]
        assert payload["parentId"] == "500"
        # Default status still applies when only parent_id is set.
        assert payload["status"] == "current"

    def test_options_status_archived(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"id": "42"})
        with patch.object(httpx.Client, "request", return_value=resp) as req:
            client.put_page(
                "42",
                "T",
                "<p/>",
                version=2,
                options=PutPageOptions(status="archived"),
            )
        payload = req.call_args[1]["json"]
        assert payload["status"] == "archived"
        assert "parentId" not in payload


class TestArchivePage:
    """Spec S27: archive_page primitive with v2-first / v1-fallback dispatch."""

    def test_v2_happy_path(self) -> None:
        client = _make_client()
        archived = {"id": "42", "status": "archived"}
        resp = _mock_response(200, archived)
        with patch.object(httpx.Client, "request", return_value=resp) as req:
            result = client.archive_page("42", message="bye")
        assert result["status"] == "archived"
        # v2 endpoint hit, single call, POST.
        assert req.call_count == 1
        method, url = req.call_args[0][0], req.call_args[0][1]
        assert method == "POST"
        assert "/wiki/api/v2/pages/42/archive" in url

    def test_v2_no_message_sends_empty_payload(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"id": "42", "status": "archived"})
        with patch.object(httpx.Client, "request", return_value=resp) as req:
            client.archive_page("42")
        payload = req.call_args[1]["json"]
        assert payload == {}

    def test_v1_fallback_on_v2_404(self) -> None:
        client = _make_client()
        # v2 POST returns 404 → must fall back to v1.
        not_found = _mock_response(404)
        # Then v1: client first GETs current title/version, then PUTs.
        v1_get = _mock_response(200, {"title": "Old", "version": {"number": 7}})
        v1_put = _mock_response(200, {"id": "42", "status": "archived"})
        responses = iter([not_found, v1_get, v1_put])

        def _next(*_a: object, **_k: object) -> MagicMock:
            return next(responses)

        with patch.object(httpx.Client, "request", side_effect=_next) as req:
            result = client.archive_page("42", message="bye")
        assert result["status"] == "archived"
        # Three calls: v2 POST → v1 GET → v1 PUT.
        assert req.call_count == 3
        v2_call, v1_get_call, v1_put_call = req.call_args_list
        assert v2_call[0][0] == "POST"
        assert "/wiki/api/v2/pages/42/archive" in v2_call[0][1]
        assert v1_get_call[0][0] == "GET"
        assert "/wiki/rest/api/content/42" in v1_get_call[0][1]
        assert v1_put_call[0][0] == "PUT"
        v1_payload = v1_put_call[1]["json"]
        assert v1_payload["status"] == "archived"
        assert v1_payload["version"]["number"] == 8  # bumped from remote 7
        assert v1_payload["version"]["message"] == "bye"
        assert v1_payload["title"] == "Old"

    def test_v1_fallback_on_v2_405(self) -> None:
        client = _make_client()
        method_not_allowed = _mock_response(405)
        v1_get = _mock_response(200, {"title": "X", "version": {"number": 1}})
        v1_put = _mock_response(200, {"id": "42", "status": "archived"})
        responses = iter([method_not_allowed, v1_get, v1_put])

        def _next(*_a: object, **_k: object) -> MagicMock:
            return next(responses)

        with patch.object(httpx.Client, "request", side_effect=_next):
            result = client.archive_page("42")
        assert result["status"] == "archived"

    def test_non_404_405_v2_failure_propagates(self) -> None:
        # A 400 must NOT trigger v1 fallback — only "endpoint not present"
        # cases (404 / 405) do.  400 is non-retryable in ``_request`` so
        # this stays fast.
        client = _make_client()
        bad_request = _mock_response(400)
        bad_request.text = "bad"
        with (
            patch.object(httpx.Client, "request", return_value=bad_request),
            pytest.raises(ConfluenceError),
        ):
            client.archive_page("42")

    def test_invalid_page_id_raises(self) -> None:
        client = _make_client()
        with pytest.raises(ConfluenceError, match="not a valid alphanumeric identifier"):
            client.archive_page("../etc/passwd")


class TestUnarchivePage:
    """Spec S27: unarchive_page primitive (symmetric to archive_page)."""

    def test_v2_happy_path(self) -> None:
        client = _make_client()
        unarchived = {"id": "42", "status": "current"}
        resp = _mock_response(200, unarchived)
        with patch.object(httpx.Client, "request", return_value=resp) as req:
            result = client.unarchive_page("42", message="back")
        assert result["status"] == "current"
        method, url = req.call_args[0][0], req.call_args[0][1]
        assert method == "POST"
        assert "/wiki/api/v2/pages/42/unarchive" in url
        assert req.call_args[1]["json"] == {"message": "back"}

    def test_v1_fallback_on_v2_404(self) -> None:
        client = _make_client()
        not_found = _mock_response(404)
        v1_get = _mock_response(200, {"title": "T", "version": {"number": 3}})
        v1_put = _mock_response(200, {"id": "42", "status": "current"})
        responses = iter([not_found, v1_get, v1_put])

        def _next(*_a: object, **_k: object) -> MagicMock:
            return next(responses)

        with patch.object(httpx.Client, "request", side_effect=_next):
            result = client.unarchive_page("42")
        assert result["status"] == "current"

    def test_invalid_page_id_raises(self) -> None:
        client = _make_client()
        with pytest.raises(ConfluenceError, match="not a valid alphanumeric identifier"):
            client.unarchive_page("../../admin")


class TestGetPageBodyFormat:
    """Spec S27: get_page accepts a body_format kwarg for non-storage retrieval."""

    def test_default_body_format_is_storage(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"id": "42"})
        with patch.object(httpx.Client, "request", return_value=resp) as req:
            client.get_page("42")
        params = req.call_args[1]["params"]
        assert params["body-format"] == "storage"

    def test_body_format_can_be_overridden(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"id": "42"})
        with patch.object(httpx.Client, "request", return_value=resp) as req:
            client.get_page("42", body_format="atlas_doc_format")
        params = req.call_args[1]["params"]
        assert params["body-format"] == "atlas_doc_format"


class TestGetBytes:
    def test_returns_content(self) -> None:
        client = _make_client()
        mock = MagicMock(spec=httpx.Response)
        mock.status_code = 200
        mock.is_success = True
        mock.content = b"binary data"
        with patch.object(httpx.Client, "request", return_value=mock):
            result = client.get_bytes("/some/attachment")
        assert result == b"binary data"


class TestContextManager:
    def test_close_clears_http_client(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"ok": True})
        with patch.object(httpx.Client, "request", return_value=resp):
            client.get("/ping")  # forces _http to be created
        assert client._http is not None  # pyright: ignore[reportPrivateUsage]
        client.close()
        assert client._http is None  # pyright: ignore[reportPrivateUsage]

    def test_context_manager_calls_close(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"ok": True})
        with (
            patch.object(httpx.Client, "request", return_value=resp),
            client,
        ):
            client.get("/ping")
        assert client._http is None  # pyright: ignore[reportPrivateUsage]


class TestDownloadAttachment:
    def test_builds_rest_download_path_from_pageid_and_id(self) -> None:
        # Issue #76: the legacy /wiki/download/attachments/... endpoint is
        # OAuth-gated on some tenants. The REST path /wiki/rest/api/content/
        # {page_id}/child/attachment/{att_id}/download accepts Basic auth.
        client = _make_client()
        attachment = {
            "id": "att637340870",
            "pageId": "637337733",
            "title": "image.png",
        }
        mock = MagicMock(spec=httpx.Response)
        mock.status_code = 200
        mock.is_success = True
        mock.content = b"png-bytes"
        captured_urls: list[str] = []

        def capture(method: str, url: str, **kw: object) -> MagicMock:
            captured_urls.append(url)
            return mock

        with patch.object(httpx.Client, "request", side_effect=capture):
            data = client.download_attachment(attachment)
        assert data == b"png-bytes"
        assert captured_urls
        assert (
            "/wiki/rest/api/content/637337733/child/attachment/att637340870/download"
            in captured_urls[0]
        )

    def test_ignores_legacy_downloadlink_fields(self) -> None:
        # Even if the v2 listing carries a downloadLink pointing at the
        # legacy /wiki/download/... path, we must build the REST URL from
        # pageId + id and ignore that field entirely.
        client = _make_client()
        attachment = {
            "id": "att999",
            "pageId": "123",
            "title": "image.png",
            "downloadLink": "/wiki/download/attachments/123/image.png?api=v2",
            "_links": {"download": "/wiki/download/attachments/123/image.png"},
        }
        mock = MagicMock(spec=httpx.Response)
        mock.status_code = 200
        mock.is_success = True
        mock.content = b"png-bytes"
        captured_urls: list[str] = []

        def capture(method: str, url: str, **kw: object) -> MagicMock:
            captured_urls.append(url)
            return mock

        with patch.object(httpx.Client, "request", side_effect=capture):
            client.download_attachment(attachment)
        assert captured_urls
        assert "/wiki/rest/api/content/123/child/attachment/att999/download" in captured_urls[0]
        assert "/wiki/download/attachments" not in captured_urls[0]

    def test_missing_pageid_raises(self) -> None:
        client = _make_client()
        attachment: dict[str, Any] = {"id": "att1", "title": "image.png"}  # no pageId
        with pytest.raises(ConfluenceError, match="pageId"):
            client.download_attachment(attachment)

    def test_missing_id_raises(self) -> None:
        client = _make_client()
        attachment: dict[str, Any] = {"pageId": "123", "title": "image.png"}  # no id
        with pytest.raises(ConfluenceError, match="'id'"):
            client.download_attachment(attachment)

    def test_path_traversal_in_id_rejected(self) -> None:
        client = _make_client()
        attachment: dict[str, Any] = {
            "id": "../admin",
            "pageId": "123",
            "title": "image.png",
        }
        with pytest.raises(ConfluenceError, match="non-alphanumeric"):
            client.download_attachment(attachment)

    def test_path_traversal_in_pageid_rejected(self) -> None:
        client = _make_client()
        attachment: dict[str, Any] = {
            "id": "att1",
            "pageId": "../../etc/passwd",
            "title": "image.png",
        }
        with pytest.raises(ConfluenceError, match="non-alphanumeric"):
            client.download_attachment(attachment)


class TestDownloadAttachmentToFile:
    """Regression: a failed download must NOT create a 0-byte stub at `dest`."""

    def test_401_does_not_create_dest_file(self, tmp_path: Path) -> None:
        client = _make_client()
        attachment = {"id": "att1", "pageId": "123", "title": "blocked.png"}
        dest = tmp_path / "blocked.png"

        # Build a fake streaming response that 401s.
        response_mock = MagicMock(spec=httpx.Response)
        response_mock.status_code = 401
        response_mock.is_success = False
        response_mock.read.return_value = b"<html>HTTP Status 401 - Unauthorized</html>"

        stream_cm = MagicMock()
        stream_cm.__enter__ = MagicMock(return_value=response_mock)
        stream_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(httpx.Client, "stream", return_value=stream_cm),
            pytest.raises(ConfluenceError, match="401"),
        ):
            client.download_attachment_to_file(attachment, dest)

        assert not dest.exists(), (
            f"failed download must not leave a stub file, got: {list(tmp_path.iterdir())}"
        )
        # No stray .part files either
        leftover = list(tmp_path.iterdir())
        assert leftover == [], f"temp .part file not cleaned up: {leftover}"

    def test_successful_download_writes_dest(self, tmp_path: Path) -> None:
        client = _make_client()
        attachment = {"id": "att1", "pageId": "123", "title": "ok.png"}
        dest = tmp_path / "ok.png"

        response_mock = MagicMock(spec=httpx.Response)
        response_mock.status_code = 200
        response_mock.is_success = True
        response_mock.iter_bytes.return_value = iter([b"chunk1", b"chunk2"])

        stream_cm = MagicMock()
        stream_cm.__enter__ = MagicMock(return_value=response_mock)
        stream_cm.__exit__ = MagicMock(return_value=False)

        with patch.object(httpx.Client, "stream", return_value=stream_cm):
            total = client.download_attachment_to_file(attachment, dest)

        assert total == 12
        assert dest.read_bytes() == b"chunk1chunk2"
        # No leftover .part files
        leftover = [p for p in tmp_path.iterdir() if p != dest]
        assert leftover == [], f"temp .part file not cleaned up: {leftover}"


class TestUploadAttachment:
    def test_successful_upload(self, tmp_path: Path) -> None:
        client = _make_client()
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG")
        resp = _mock_response(200, {"results": [{"id": "att1"}]})
        with patch.object(httpx.Client, "request", return_value=resp):
            result = client.upload_attachment("page123", f)
        assert isinstance(result, dict)

    def test_upload_4xx_raises(self, tmp_path: Path) -> None:
        client = _make_client()
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG")
        resp = _mock_response(400)
        with (
            patch.object(httpx.Client, "request", return_value=resp),
            pytest.raises(ConfluenceError, match="400"),
        ):
            client.upload_attachment("page123", f)

    def test_upload_non_dict_json_raises(self, tmp_path: Path) -> None:
        client = _make_client()
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG")
        mock = MagicMock(spec=httpx.Response)
        mock.status_code = 200
        mock.is_success = True
        mock.json.return_value = ["not", "a", "dict"]
        with (
            patch.object(httpx.Client, "request", return_value=mock),
            pytest.raises(ConfluenceError, match="Expected JSON object"),
        ):
            client.upload_attachment("page123", f)


class TestPostPageNonDict:
    def test_post_page_non_dict_json_raises(self) -> None:
        client = _make_client()
        mock = MagicMock(spec=httpx.Response)
        mock.status_code = 200
        mock.is_success = True
        mock.json.return_value = ["not", "a", "dict"]
        with (
            patch.object(httpx.Client, "request", return_value=mock),
            pytest.raises(ConfluenceError, match="Expected JSON object"),
        ):
            client.post_page(space_id="s1", parent_id=None, title="T", body="<p/>")


class TestPutPageNonDict:
    def test_put_page_non_dict_json_raises(self) -> None:
        client = _make_client()
        mock = MagicMock(spec=httpx.Response)
        mock.status_code = 200
        mock.is_success = True
        mock.json.return_value = "just a string"
        with (
            patch.object(httpx.Client, "request", return_value=mock),
            pytest.raises(ConfluenceError, match="Expected JSON object"),
        ):
            client.put_page("42", "Title", "<p/>", version=2)


class TestIdValidation:
    def test_invalid_page_id_raises(self) -> None:
        client = _make_client()
        with pytest.raises(ConfluenceError, match="not a valid alphanumeric identifier"):
            client.get_page("../../admin")

    def test_invalid_folder_id_raises(self) -> None:
        client = _make_client()
        with pytest.raises(ConfluenceError, match="not a valid alphanumeric identifier"):
            client.get_folder("../etc")

    def test_invalid_page_id_in_upload_raises(self, tmp_path: Path) -> None:
        client = _make_client()
        f = tmp_path / "file.png"
        f.write_bytes(b"data")
        with pytest.raises(ConfluenceError, match="not a valid alphanumeric identifier"):
            client.upload_attachment("123/comment", f)

    def test_valid_numeric_page_id_accepted(self) -> None:
        client = _make_client()
        resp = _mock_response(200, {"id": "99", "version": {"number": 1}})
        with patch.object(httpx.Client, "request", return_value=resp):
            result = client.get_page("12345")
        assert result["id"] == "99"

    def test_put_page_invalid_id_raises(self) -> None:
        client = _make_client()
        with pytest.raises(ConfluenceError, match="not a valid alphanumeric identifier"):
            client.put_page("../../etc/passwd", "Title", "<p/>", version=1)


class TestSSRF:
    def test_assert_relative_api_path_accepts_relative(self) -> None:
        # Should not raise
        assert_relative_api_path("/wiki/api/v2/pages?cursor=abc", "_links.next")

    def test_assert_relative_api_path_rejects_absolute_url(self) -> None:
        with pytest.raises(ConfluenceError, match="non-relative URL"):
            assert_relative_api_path("https://attacker.example/steal", "_links.next")

    def test_assert_relative_api_path_rejects_scheme(self) -> None:
        with pytest.raises(ConfluenceError, match="non-relative URL"):
            assert_relative_api_path("file:///etc/passwd", "_links.download")

    def test_assert_relative_api_path_rejects_non_slash_start(self) -> None:
        with pytest.raises(ConfluenceError, match="non-relative URL"):
            assert_relative_api_path("relative/path/without/slash", "_links.next")

    def test_download_attachment_rejects_path_traversal_id(self) -> None:
        # SSRF guard now happens at URL-construction time: the attachment
        # id and pageId are validated as alphanumeric before being interpolated
        # into the REST path.
        client = _make_client()
        attachment = {
            "id": "../../etc/passwd",
            "pageId": "123",
            "title": "file.png",
        }
        with pytest.raises(ConfluenceError, match="non-alphanumeric"):
            client.download_attachment(attachment)

    def test_list_page_attachments_rejects_absolute_next_url(self) -> None:
        client = _make_client()
        # First page returns a foreign absolute URL as the next link
        page1 = {
            "results": [{"id": "att1"}],
            "_links": {"next": "https://attacker.example/steal"},
        }
        resp = _mock_response(200, page1)
        with (
            patch.object(httpx.Client, "request", return_value=resp),
            pytest.raises(ConfluenceError, match="non-relative URL"),
        ):
            client.list_page_attachments("12345")


class TestPaginationGuard:
    """Bounded pagination loops raise instead of looping forever (#79 fallout)."""

    def test_list_page_attachments_raises_after_max_iterations(self) -> None:
        client = _make_client()
        # Every page advertises a next page — the guard must stop the loop.
        endless = _mock_response(
            200,
            {
                "results": [{"id": "att"}],
                "_links": {"next": "/wiki/rest/api/content/12345/child/attachment?cursor=x"},
            },
        )
        with (
            patch.object(httpx.Client, "request", return_value=endless),
            pytest.raises(ConfluenceError, match="pagination exceeded"),
        ):
            client.list_page_attachments("12345")

    def test_list_page_attachments_preserves_next_url_query_string(self) -> None:
        """Regression: httpx ``params={}`` strips the URL's query string (#79).

        The follow-up paginated request must use ``params=None`` so the cursor
        embedded in ``_links.next`` survives.
        """
        client = _make_client()

        def make_response(next_link: str | None) -> MagicMock:
            return _mock_response(
                200,
                {
                    "results": [{"id": "a"}],
                    "_links": ({"next": next_link} if next_link else {}),
                },
            )

        captured_urls: list[str] = []

        def fake_request(*args: Any, **kwargs: Any) -> MagicMock:
            # Capture the final URL httpx would build for each call.
            url = args[1] if len(args) >= 2 else kwargs["url"]
            params: Any = kwargs.get("params")  # pyright: ignore[reportAny]
            built = httpx.Client().build_request("GET", url, params=params)
            captured_urls.append(str(built.url))
            if len(captured_urls) == 1:
                return make_response("/wiki/rest/api/content/12345/child/attachment?cursor=ABC")
            return make_response(None)

        with patch.object(httpx.Client, "request", side_effect=fake_request):
            client.list_page_attachments("12345")

        assert "cursor=ABC" in captured_urls[1], (
            f"cursor was stripped from follow-up request: {captured_urls!r}"
        )


class TestTokenRefreshOn401:
    def test_401_triggers_token_refresh_and_retry(self) -> None:
        client = _make_client()
        call_count = 0

        def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_response(401)
            return _mock_response(200, {"ok": True})

        with (
            patch("mdd.confluence.client.time.sleep"),
            patch.object(httpx.Client, "request", side_effect=side_effect),
        ):
            result = client.get("/test")

        assert result["ok"] is True
        assert call_count == 2  # initial 401 + one retry after token refresh

    def test_401_twice_raises(self) -> None:
        client = _make_client()
        with (
            patch("mdd.confluence.client.time.sleep"),
            patch.object(httpx.Client, "request", return_value=_mock_response(401)),
            pytest.raises(ConfluenceError, match="401"),
        ):
            client.get("/test")
