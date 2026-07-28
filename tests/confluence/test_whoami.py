"""Unit tests for the whoami helpers."""

from __future__ import annotations

from mdd.confluence.managed import PublisherEntry
from mdd.confluence.whoami import (
    _format_publisher_lines,  # pyright: ignore[reportPrivateUsage]
    _get_str,  # pyright: ignore[reportPrivateUsage]
)


def test_get_str_returns_value_when_string() -> None:
    assert _get_str({"accountId": "abc"}, "accountId") == "abc"


def test_get_str_returns_empty_for_missing_key() -> None:
    assert _get_str({}, "accountId") == ""


def test_get_str_returns_empty_for_non_string_value() -> None:
    assert _get_str({"accountId": 123}, "accountId") == ""
    assert _get_str({"accountId": None}, "accountId") == ""


def test_format_publisher_lines_marks_match() -> None:
    pubs = [PublisherEntry(name="Bot", account_ids=["abc", "xyz"])]
    lines = _format_publisher_lines(pubs, account_id="abc")
    assert any("match!" in line for line in lines)
    assert any("(no match)" in line for line in lines)


def test_format_publisher_lines_no_account_ids() -> None:
    pubs = [PublisherEntry(name="Bot", account_ids=[])]
    lines = _format_publisher_lines(pubs, account_id="abc")
    assert lines == ["  Bot                            (no account IDs configured)"]


def test_format_publisher_lines_no_match_when_id_mismatch() -> None:
    pubs = [PublisherEntry(name="Bot", account_ids=["other"])]
    lines = _format_publisher_lines(pubs, account_id="abc")
    assert all("(no match)" in line for line in lines)


def test_format_publisher_lines_multiple_publishers() -> None:
    pubs = [
        PublisherEntry(name="A", account_ids=["a1"]),
        PublisherEntry(name="B", account_ids=["b1", "b2"]),
    ]
    lines = _format_publisher_lines(pubs, account_id="b2")
    assert len(lines) == 3
    assert "match!" in lines[2]
