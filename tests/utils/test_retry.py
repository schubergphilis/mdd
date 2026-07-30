"""Tests for mdd.utils.retry — shared HTTP retry-decision helpers."""

from __future__ import annotations

import datetime
import email.utils

import httpx
import pytest

from mdd.utils.retry import backoff_for_response, jittered_delay, parse_retry_after, should_retry


def _response(status_code: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status_code=status_code, headers=headers or {})


class TestShouldRetry:
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_retryable_statuses(self, status: int) -> None:
        assert should_retry(_response(status)) is True

    @pytest.mark.parametrize("status", [200, 201, 301, 400, 401, 403, 404, 409])
    def test_non_retryable_statuses(self, status: int) -> None:
        assert should_retry(_response(status)) is False


class TestJitteredDelay:
    def test_within_ten_percent_band(self) -> None:
        for _ in range(100):
            assert 4.0 <= jittered_delay(4.0) <= 4.4

    def test_zero_delay_stays_zero(self) -> None:
        assert jittered_delay(0.0) == 0.0


class TestParseRetryAfter:
    def test_absent_header(self) -> None:
        assert parse_retry_after(_response(429)) is None

    def test_integer_seconds(self) -> None:
        assert parse_retry_after(_response(429, {"Retry-After": "30"})) == 30.0

    def test_surrounding_whitespace(self) -> None:
        assert parse_retry_after(_response(429, {"Retry-After": "  12  "})) == 12.0

    def test_http_date_form(self) -> None:
        future = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(seconds=45)
        header = email.utils.format_datetime(future, usegmt=True)
        delay = parse_retry_after(_response(429, {"Retry-After": header}))
        assert delay is not None
        assert 40.0 <= delay <= 45.0

    def test_http_date_in_the_past_clamps_to_zero(self) -> None:
        past = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(seconds=60)
        header = email.utils.format_datetime(past, usegmt=True)
        assert parse_retry_after(_response(429, {"Retry-After": header})) == 0.0

    def test_unparseable_header(self) -> None:
        assert parse_retry_after(_response(429, {"Retry-After": "soon"})) is None

    def test_empty_header(self) -> None:
        assert parse_retry_after(_response(429, {"Retry-After": ""})) is None


class TestBackoffForResponse:
    def test_429_honours_retry_after(self) -> None:
        assert backoff_for_response(_response(429, {"Retry-After": "5"}), 8.0) == 5.0

    def test_429_caps_retry_after_at_60(self) -> None:
        assert backoff_for_response(_response(429, {"Retry-After": "600"}), 8.0) == 60.0

    def test_429_without_header_uses_jittered_schedule(self) -> None:
        delay = backoff_for_response(_response(429), 8.0)
        assert 8.0 <= delay <= 8.8

    def test_503_ignores_retry_after(self) -> None:
        delay = backoff_for_response(_response(503, {"Retry-After": "5"}), 2.0)
        assert 2.0 <= delay <= 2.2
