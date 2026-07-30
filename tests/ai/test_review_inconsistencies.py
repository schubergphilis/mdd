"""Tests for mdd.ai.judges inconsistency mode."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from mdd.ai.judges import (
    _parse_inconsistency_response as _parse_inconsistency_response,  # pyright: ignore[reportPrivateUsage]
)
from mdd.ai.judges import judge_inconsistency_pair
from mdd.ai.models import ChatResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chat_result(text: str, cached: bool = False) -> ChatResult:
    return ChatResult(
        text=text,
        cached=cached,
        prompt_tokens=20,
        completion_tokens=10,
        cost_usd=None,
    )


def _make_mock_client(response_text: str, cached: bool = False) -> MagicMock:
    mock = MagicMock()
    mock.chat.return_value = _make_chat_result(response_text, cached=cached)
    mock.summary.api_calls = 1
    mock.summary.cached_calls = 0
    return mock


CONTRADICTIONS_RESPONSE = json.dumps(
    {
        "contradictions": [
            {
                "page_a_quote": "blue-green is the default",
                "page_b_quote": "canary is the default for production",
                "issue": "Conflicting default rollout strategy",
            }
        ]
    }
)

EMPTY_CONTRADICTIONS_RESPONSE = json.dumps({"contradictions": []})


# ---------------------------------------------------------------------------
# _parse_inconsistency_response
# ---------------------------------------------------------------------------


class TestParseInconsistencyResponse:
    def test_non_empty_contradictions_returns_finding(self) -> None:
        path_a = Path("Process/Deployment.md")
        path_b = Path("Platform/Deployment.md")
        finding = _parse_inconsistency_response(CONTRADICTIONS_RESPONSE, path_a, path_b)
        assert finding is not None
        assert len(finding.contradictions) == 1
        assert finding.contradictions[0]["issue"] == "Conflicting default rollout strategy"
        assert finding.path_a == path_a
        assert finding.path_b == path_b

    def test_empty_contradictions_returns_none(self) -> None:
        finding = _parse_inconsistency_response(
            EMPTY_CONTRADICTIONS_RESPONSE, Path("A.md"), Path("B.md")
        )
        assert finding is None

    def test_missing_contradictions_field_returns_none(self) -> None:
        raw = json.dumps({"something": "else"})
        finding = _parse_inconsistency_response(raw, Path("A.md"), Path("B.md"))
        assert finding is None

    def test_invalid_json_returns_none(self) -> None:
        finding = _parse_inconsistency_response("not json at all", Path("A.md"), Path("B.md"))
        assert finding is None

    def test_non_dict_json_returns_none(self) -> None:
        finding = _parse_inconsistency_response("[1, 2]", Path("A.md"), Path("B.md"))
        assert finding is None

    def test_multiple_contradictions(self) -> None:
        raw = json.dumps(
            {
                "contradictions": [
                    {
                        "page_a_quote": "quote 1a",
                        "page_b_quote": "quote 1b",
                        "issue": "issue 1",
                    },
                    {
                        "page_a_quote": "quote 2a",
                        "page_b_quote": "quote 2b",
                        "issue": "issue 2",
                    },
                ]
            }
        )
        finding = _parse_inconsistency_response(raw, Path("A.md"), Path("B.md"))
        assert finding is not None
        assert len(finding.contradictions) == 2

    def test_non_dict_items_in_list_skipped(self) -> None:
        entry = {"page_a_quote": "q", "page_b_quote": "r", "issue": "i"}
        raw = json.dumps({"contradictions": ["not a dict", entry]})
        finding = _parse_inconsistency_response(raw, Path("A.md"), Path("B.md"))
        # The non-dict item is skipped; the valid one is kept
        assert finding is not None
        assert len(finding.contradictions) == 1


# ---------------------------------------------------------------------------
# judge_inconsistency_pair
# ---------------------------------------------------------------------------


class TestJudgeInconsistencyPair:
    def test_contradictions_found_returns_finding(self) -> None:
        mock = _make_mock_client(CONTRADICTIONS_RESPONSE)
        finding = judge_inconsistency_pair(
            Path("A.md"),
            "Content A",
            Path("B.md"),
            "Content B",
            client=mock,
            hash_a=b"hash_a",
            hash_b=b"hash_b",
        )
        assert finding is not None
        assert len(finding.contradictions) == 1

    def test_no_contradictions_returns_none(self) -> None:
        mock = _make_mock_client(EMPTY_CONTRADICTIONS_RESPONSE)
        finding = judge_inconsistency_pair(
            Path("A.md"),
            "Content A",
            Path("B.md"),
            "Content B",
            client=mock,
            hash_a=b"hash_a",
            hash_b=b"hash_b",
        )
        assert finding is None

    def test_cache_key_extra_uses_both_hashes(self) -> None:
        """Different hash pairs produce different cache_key_extra values."""
        mock = _make_mock_client(EMPTY_CONTRADICTIONS_RESPONSE)

        judge_inconsistency_pair(
            Path("A.md"),
            "body",
            Path("B.md"),
            "body",
            client=mock,
            hash_a=b"hash_a",
            hash_b=b"hash_b",
        )
        extra_1 = mock.chat.call_args.kwargs.get("cache_key_extra")

        judge_inconsistency_pair(
            Path("A.md"),
            "body",
            Path("C.md"),
            "body",
            client=mock,
            hash_a=b"hash_a",
            hash_b=b"hash_c",
        )
        extra_2 = mock.chat.call_args.kwargs.get("cache_key_extra")

        assert extra_1 != extra_2

    def test_mode_tag_differs_from_duplicates(self) -> None:
        """The cache extra for inconsistencies differs from duplicates for same hashes."""
        from mdd.ai.judges import judge_duplicate_pair

        mock = _make_mock_client(EMPTY_CONTRADICTIONS_RESPONSE)

        judge_inconsistency_pair(
            Path("A.md"),
            "body",
            Path("B.md"),
            "body",
            client=mock,
            hash_a=b"hash_a",
            hash_b=b"hash_b",
        )
        extra_incon = mock.chat.call_args.kwargs.get("cache_key_extra")

        judge_duplicate_pair(
            Path("A.md"),
            "body",
            Path("B.md"),
            "body",
            client=mock,
            hash_a=b"hash_a",
            hash_b=b"hash_b",
        )
        extra_dup = mock.chat.call_args.kwargs.get("cache_key_extra")

        assert extra_incon != extra_dup

    def test_prompt_includes_paths(self) -> None:
        mock = _make_mock_client(EMPTY_CONTRADICTIONS_RESPONSE)
        judge_inconsistency_pair(
            Path("Process/Deployment.md"),
            "content A",
            Path("Platform/Deployment.md"),
            "content B",
            client=mock,
            hash_a=b"h1",
            hash_b=b"h2",
        )
        user_msg = mock.chat.call_args.kwargs.get("user", "")
        assert "Process/Deployment.md" in user_msg
        assert "Platform/Deployment.md" in user_msg
