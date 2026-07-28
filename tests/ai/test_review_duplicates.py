"""Tests for mdd.ai.judges duplicate mode and mdd.ai.review integration (spec S22)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from mdd.ai.judges import (
    _parse_duplicate_response as _parse_duplicate_response,  # pyright: ignore[reportPrivateUsage]
)
from mdd.ai.judges import judge_duplicate_pair
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


HIGH_OVERLAP_RESPONSE = json.dumps(
    {
        "overlap": "high",
        "summary": "Both pages cover onboarding steps for new employees.",
        "shared_sections": ["laptop provisioning", "IT portal access"],
        "suggested_action": "Merge into 'New Hire Setup.md' and deprecate 'Onboarding.md'.",
    }
)

MEDIUM_OVERLAP_RESPONSE = json.dumps(
    {
        "overlap": "medium",
        "summary": "Some shared sections but each has unique content.",
        "shared_sections": ["laptop setup"],
        "suggested_action": "Add cross-references between the two pages.",
    }
)

LOW_OVERLAP_RESPONSE = json.dumps(
    {
        "overlap": "low",
        "summary": "Minimal shared content.",
        "shared_sections": [],
        "suggested_action": "",
    }
)

NONE_OVERLAP_RESPONSE = json.dumps(
    {
        "overlap": "none",
        "summary": "No meaningful overlap.",
        "shared_sections": [],
        "suggested_action": "",
    }
)


# ---------------------------------------------------------------------------
# _parse_duplicate_response
# ---------------------------------------------------------------------------


class TestParseDuplicateResponse:
    def test_high_overlap_returns_finding(self) -> None:
        path_a = Path("Engineering/Onboarding.md")
        path_b = Path("Engineering/New Hire Setup.md")
        finding = _parse_duplicate_response(HIGH_OVERLAP_RESPONSE, path_a, path_b)
        assert finding is not None
        assert finding.overlap == "high"
        assert "laptop provisioning" in finding.shared_sections
        assert "IT portal access" in finding.shared_sections
        assert path_a == finding.path_a
        assert path_b == finding.path_b

    def test_medium_overlap_returns_none(self) -> None:
        finding = _parse_duplicate_response(MEDIUM_OVERLAP_RESPONSE, Path("A.md"), Path("B.md"))
        assert finding is None

    def test_low_overlap_returns_none(self) -> None:
        finding = _parse_duplicate_response(LOW_OVERLAP_RESPONSE, Path("A.md"), Path("B.md"))
        assert finding is None

    def test_none_overlap_returns_none(self) -> None:
        finding = _parse_duplicate_response(NONE_OVERLAP_RESPONSE, Path("A.md"), Path("B.md"))
        assert finding is None

    def test_invalid_json_returns_none(self) -> None:
        finding = _parse_duplicate_response("not json", Path("A.md"), Path("B.md"))
        assert finding is None

    def test_missing_overlap_field_returns_none(self) -> None:
        raw = json.dumps({"summary": "No overlap field here"})
        finding = _parse_duplicate_response(raw, Path("A.md"), Path("B.md"))
        assert finding is None

    def test_non_dict_json_returns_none(self) -> None:
        finding = _parse_duplicate_response("[1, 2, 3]", Path("A.md"), Path("B.md"))
        assert finding is None

    def test_empty_response_returns_none(self) -> None:
        finding = _parse_duplicate_response("", Path("A.md"), Path("B.md"))
        assert finding is None

    def test_shared_sections_non_list_handled(self) -> None:
        raw = json.dumps(
            {
                "overlap": "high",
                "summary": "High overlap",
                "shared_sections": "not a list",
                "suggested_action": "merge",
            }
        )
        finding = _parse_duplicate_response(raw, Path("A.md"), Path("B.md"))
        assert finding is not None
        assert finding.shared_sections == []


# ---------------------------------------------------------------------------
# judge_duplicate_pair
# ---------------------------------------------------------------------------


class TestJudgeDuplicatePair:
    def test_high_overlap_returns_finding(self) -> None:
        mock = _make_mock_client(HIGH_OVERLAP_RESPONSE)
        finding = judge_duplicate_pair(
            Path("A.md"),
            "Content A",
            Path("B.md"),
            "Content B",
            client=mock,
            hash_a=b"hash_a",
            hash_b=b"hash_b",
        )
        assert finding is not None
        assert finding.overlap == "high"

    def test_low_overlap_returns_none(self) -> None:
        mock = _make_mock_client(LOW_OVERLAP_RESPONSE)
        finding = judge_duplicate_pair(
            Path("A.md"),
            "Content A",
            Path("B.md"),
            "Content B",
            client=mock,
            hash_a=b"hash_a",
            hash_b=b"hash_b",
        )
        assert finding is None

    def test_model_override_passed_to_client(self) -> None:
        mock = _make_mock_client(HIGH_OVERLAP_RESPONSE)
        judge_duplicate_pair(
            Path("A.md"),
            "Content A",
            Path("B.md"),
            "Content B",
            client=mock,
            hash_a=b"h1",
            hash_b=b"h2",
            model="custom-model",
        )
        call_kwargs = mock.chat.call_args.kwargs
        assert call_kwargs.get("model") == "custom-model"

    def test_cache_key_extra_uses_both_hashes(self) -> None:
        """Calling with different hash pairs results in different cache_key_extra."""
        mock = _make_mock_client(LOW_OVERLAP_RESPONSE)

        judge_duplicate_pair(
            Path("A.md"),
            "body",
            Path("B.md"),
            "body",
            client=mock,
            hash_a=b"hash_a",
            hash_b=b"hash_b",
        )
        extra_1 = mock.chat.call_args.kwargs.get("cache_key_extra")

        judge_duplicate_pair(
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

    def test_prompt_includes_paths(self) -> None:
        mock = _make_mock_client(LOW_OVERLAP_RESPONSE)
        judge_duplicate_pair(
            Path("Engineering/Onboarding.md"),
            "body A",
            Path("Engineering/New Hire Setup.md"),
            "body B",
            client=mock,
            hash_a=b"h1",
            hash_b=b"h2",
        )
        user_msg = mock.chat.call_args.kwargs.get("user", "")
        assert "Engineering/Onboarding.md" in user_msg
        assert "Engineering/New Hire Setup.md" in user_msg

    def test_cached_result_accepted(self) -> None:
        mock = _make_mock_client(HIGH_OVERLAP_RESPONSE, cached=True)
        finding = judge_duplicate_pair(
            Path("A.md"),
            "body",
            Path("B.md"),
            "body",
            client=mock,
            hash_a=b"h1",
            hash_b=b"h2",
        )
        assert finding is not None
