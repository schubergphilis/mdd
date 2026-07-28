"""Tests for mdd.ai.retry — retry decorator with Retry-After support (spec S20)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import openai
import pytest

from mdd.ai.models import AiRateLimitedError, AiServerError
from mdd.ai.retry import RETRY_AFTER_CAP, with_retry


def _make_rate_limit_error(retry_after: str | None = None) -> openai.RateLimitError:
    """Build a minimal RateLimitError with optional Retry-After header."""
    response = MagicMock()
    response.status_code = 429
    if retry_after is not None:
        response.headers = {"retry-after": retry_after}
    else:
        response.headers = {}
    return openai.RateLimitError(message="rate limited", response=response, body={})


def _make_status_error(status_code: int) -> openai.APIStatusError:
    response = MagicMock()
    response.status_code = status_code
    return openai.APIStatusError(message=f"error {status_code}", response=response, body={})


class TestWithRetry:
    def test_success_on_first_attempt(self) -> None:
        calls = 0

        @with_retry
        def fn() -> str:
            nonlocal calls
            calls += 1
            return "ok"

        assert fn() == "ok"
        assert calls == 1

    def test_retries_on_rate_limit(self) -> None:
        call_count = 0

        @with_retry
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise _make_rate_limit_error()
            return "done"

        with patch("mdd.ai.retry.time.sleep"):
            result = fn()

        assert result == "done"
        assert call_count == 3

    def test_retries_on_5xx(self) -> None:
        call_count = 0

        @with_retry
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise _make_status_error(503)
            return "ok"

        with patch("mdd.ai.retry.time.sleep"):
            result = fn()

        assert result == "ok"
        assert call_count == 2

    def test_raises_ai_rate_limited_after_all_retries(self) -> None:
        @with_retry
        def fn() -> str:
            raise _make_rate_limit_error()

        with patch("mdd.ai.retry.time.sleep"), pytest.raises(AiRateLimitedError):
            fn()

    def test_raises_ai_server_error_after_all_retries(self) -> None:
        @with_retry
        def fn() -> str:
            raise _make_status_error(500)

        with patch("mdd.ai.retry.time.sleep"), pytest.raises(AiServerError):
            fn()

    def test_retries_on_connection_error(self) -> None:
        call_count = 0

        @with_retry
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise openai.APIConnectionError(request=MagicMock())
            return "ok"

        with patch("mdd.ai.retry.time.sleep"):
            result = fn()

        assert result == "ok"

    def test_no_retry_on_4xx(self) -> None:
        """4xx errors (except 429) should not be retried."""
        call_count = 0

        @with_retry
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            raise _make_status_error(400)

        with pytest.raises(openai.APIStatusError):
            fn()

        assert call_count == 1

    def test_no_retry_on_auth_error(self) -> None:
        call_count = 0

        @with_retry
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            response = MagicMock()
            response.status_code = 401
            raise openai.AuthenticationError(message="unauth", response=response, body={})

        with pytest.raises(openai.AuthenticationError):
            fn()

        assert call_count == 1

    def test_retry_after_header_respected(self) -> None:
        """Retry-After: 5 should cause a 5s sleep (plus jitter) on first retry."""
        call_count = 0
        sleep_calls: list[float] = []

        @with_retry
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_rate_limit_error(retry_after="5")
            return "ok"

        def record_sleep(s: float) -> None:
            sleep_calls.append(s)

        with patch("mdd.ai.retry.time.sleep", side_effect=record_sleep):
            result = fn()

        assert result == "ok"
        assert len(sleep_calls) == 1
        # Should be close to 5s (possibly with jitter)
        assert sleep_calls[0] >= 5.0
        assert sleep_calls[0] <= 5.0 * 1.1 + 0.01  # 10% jitter cap

    def test_retry_after_capped_at_60s(self) -> None:
        """Retry-After: 300 should be capped at 60s."""
        call_count = 0
        sleep_calls: list[float] = []

        @with_retry
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_rate_limit_error(retry_after="300")
            return "ok"

        def record_sleep(s: float) -> None:
            sleep_calls.append(s)

        with patch("mdd.ai.retry.time.sleep", side_effect=record_sleep):
            result = fn()

        assert result == "ok"
        assert sleep_calls[0] <= RETRY_AFTER_CAP * 1.1 + 0.01

    def test_total_attempts_is_five(self) -> None:
        """Spec: 5 attempts total (1 initial + 4 retries)."""
        call_count = 0

        @with_retry
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            raise _make_rate_limit_error()

        with patch("mdd.ai.retry.time.sleep"), pytest.raises(AiRateLimitedError):
            fn()

        assert call_count == 5
