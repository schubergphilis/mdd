"""Tests for mdd.confluence.client retry behaviour (monkeypatched transport)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from mdd.confluence.client import ConfluenceClient, ConfluenceError


def _make_client() -> ConfluenceClient:
    return ConfluenceClient(
        base_url="https://example.atlassian.net",
        username="user@example.com",
        token_resolver=lambda: "test-token",
    )


def _mock_response(
    status_code: int,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.is_success = 200 <= status_code < 300
    mock.text = ""
    # Set up headers as a dict-like mock (Retry-After support, spec S16)
    header_dict: dict[str, str] = headers or {}

    def _headers_get(key: str, default: str | None = None) -> str | None:
        return header_dict.get(key, default)

    mock.headers = MagicMock()
    mock.headers.get = _headers_get
    if json_body is not None:
        mock.json.return_value = json_body
        mock.content = b"{}"
    return mock


class TestRetryOn429:
    def test_429_retries_then_raises(self) -> None:
        client = _make_client()
        response_429 = _mock_response(429)

        with (
            patch("mdd.confluence.client.time.sleep") as mock_sleep,
            patch.object(httpx.Client, "request", return_value=response_429),
            pytest.raises(ConfluenceError),
        ):
            client.get("/test")

        # 5 attempts total (spec S09): 1 initial + 4 retries with delays 1,2,4,8.
        # The last attempt has delay=None so no sleep before it — sleep is called 4 times.
        assert mock_sleep.call_count == 4

    def test_503_retries(self) -> None:
        client = _make_client()
        response_503 = _mock_response(503)

        with (
            patch("mdd.confluence.client.time.sleep"),
            patch.object(httpx.Client, "request", return_value=response_503),
            pytest.raises(ConfluenceError),
        ):
            client.get("/test")


class TestNoRetryOn4xx:
    def test_400_raises_immediately(self) -> None:
        client = _make_client()
        response_400 = _mock_response(400)

        with (
            patch("mdd.confluence.client.time.sleep") as mock_sleep,
            patch.object(httpx.Client, "request", return_value=response_400),
            pytest.raises(ConfluenceError, match="400"),
        ):
            client.get("/test")

        # No sleep — no retry on 400
        mock_sleep.assert_not_called()

    def test_401_raises_immediately(self) -> None:
        client = _make_client()
        response_401 = _mock_response(401)

        with (
            patch("mdd.confluence.client.time.sleep") as mock_sleep,
            patch.object(httpx.Client, "request", return_value=response_401),
            pytest.raises(ConfluenceError, match="401"),
        ):
            client.get("/test")

        mock_sleep.assert_not_called()

    def test_404_raises_immediately(self) -> None:
        client = _make_client()
        response_404 = _mock_response(404)

        with (
            patch("mdd.confluence.client.time.sleep") as mock_sleep,
            patch.object(httpx.Client, "request", return_value=response_404),
            pytest.raises(ConfluenceError, match="404"),
        ):
            client.get("/test")

        mock_sleep.assert_not_called()


class TestSuccessResponse:
    def test_200_returns_json(self) -> None:
        client = _make_client()
        response_200 = _mock_response(200, json_body={"id": "123", "title": "Test"})

        with patch.object(httpx.Client, "request", return_value=response_200):
            result = client.get("/wiki/api/v2/pages/123")

        assert result["id"] == "123"
        assert result["title"] == "Test"


class TestConnectErrorRetry:
    def test_connect_error_retries_then_raises(self) -> None:
        client = _make_client()

        with (
            patch("mdd.confluence.client.time.sleep") as mock_sleep,
            patch.object(
                httpx.Client,
                "request",
                side_effect=httpx.ConnectError("Connection refused"),
            ),
            pytest.raises(ConfluenceError),
        ):
            client.get("/test")

        # 5 attempts total (spec S09): 1 initial + 4 retries; sleep before each retry.
        assert mock_sleep.call_count == 4

    def test_connect_error_then_success(self) -> None:
        client = _make_client()
        success = _mock_response(200, json_body={"ok": True})

        call_count = 0

        def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.ConnectError("temporary failure")
            return success

        with (
            patch("mdd.confluence.client.time.sleep"),
            patch.object(httpx.Client, "request", side_effect=side_effect),
        ):
            result = client.get("/test")

        assert result["ok"] is True


class TestTimeoutErrorRetry:
    """Issue #79: TimeoutException (read/connect/write/pool) should retry and surface clearly."""

    def test_read_timeout_retries_then_raises(self) -> None:
        client = _make_client()

        with (
            patch("mdd.confluence.client.time.sleep") as mock_sleep,
            patch.object(
                httpx.Client,
                "request",
                side_effect=httpx.ReadTimeout("read timed out"),
            ),
            pytest.raises(ConfluenceError, match="ReadTimeout"),
        ):
            client.get("/test")

        # Same retry budget as ConnectError: 5 attempts, 4 sleeps.
        assert mock_sleep.call_count == 4

    def test_pool_timeout_retries_then_raises(self) -> None:
        client = _make_client()

        with (
            patch("mdd.confluence.client.time.sleep"),
            patch.object(
                httpx.Client,
                "request",
                side_effect=httpx.PoolTimeout("pool exhausted"),
            ),
            pytest.raises(ConfluenceError, match="PoolTimeout"),
        ):
            client.get("/test")


class TestRetryAfterHeader:
    """spec S16: 429 with Retry-After must honour the header value (capped at 60 s)."""

    def test_429_with_retry_after_uses_header_value(self) -> None:
        client = _make_client()
        # Return 429 with Retry-After: 5 on every attempt
        response_429 = _mock_response(429, headers={"Retry-After": "5"})

        sleep_calls: list[float] = []

        with (
            patch("mdd.confluence.client.time.sleep", side_effect=sleep_calls.append),
            patch.object(httpx.Client, "request", return_value=response_429),
            pytest.raises(ConfluenceError),
        ):
            client.get("/test")

        # All sleep calls must be exactly 5 seconds (no jitter on Retry-After path)
        assert len(sleep_calls) == 4
        for s in sleep_calls:
            assert s == 5.0, f"Expected 5.0, got {s}"

    def test_429_with_retry_after_capped_at_60(self) -> None:
        client = _make_client()
        response_429 = _mock_response(429, headers={"Retry-After": "120"})

        sleep_calls: list[float] = []

        with (
            patch("mdd.confluence.client.time.sleep", side_effect=sleep_calls.append),
            patch.object(httpx.Client, "request", return_value=response_429),
            pytest.raises(ConfluenceError),
        ):
            client.get("/test")

        # Must cap at 60 regardless of the header value
        for s in sleep_calls:
            assert s == 60.0, f"Expected 60.0 (capped), got {s}"

    def test_429_without_retry_after_falls_to_schedule(self) -> None:
        client = _make_client()
        # No Retry-After header — falls to the fixed schedule with jitter
        response_429 = _mock_response(429)

        sleep_calls: list[float] = []

        with (
            patch("mdd.confluence.client.time.sleep", side_effect=sleep_calls.append),
            patch.object(httpx.Client, "request", return_value=response_429),
            pytest.raises(ConfluenceError),
        ):
            client.get("/test")

        # 4 sleeps matching the schedule (1, 2, 4, 8) +/- 10% jitter
        assert len(sleep_calls) == 4
        schedule = (1, 2, 4, 8)
        for actual, expected in zip(sleep_calls, schedule, strict=True):
            assert expected <= actual <= expected * 1.1 + 0.01, (
                f"Expected ~{expected}, got {actual}"
            )

    def test_503_not_affected_by_retry_after_logic(self) -> None:
        """503 uses the standard schedule (no Retry-After special case)."""
        client = _make_client()
        response_503 = _mock_response(503)

        with (
            patch("mdd.confluence.client.time.sleep"),
            patch.object(httpx.Client, "request", return_value=response_503),
            pytest.raises(ConfluenceError),
        ):
            client.get("/test")
