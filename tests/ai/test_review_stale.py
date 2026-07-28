"""Tests for mdd.ai.judges stale mode and review orchestrator (spec S22)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mdd.ai.judges import (
    _parse_stale_response as _parse_stale_response,  # pyright: ignore[reportPrivateUsage]
)
from mdd.ai.judges import judge_stale_candidate
from mdd.ai.models import ChatResult
from mdd.ai.review import ReviewConfig, run_review
from mdd.ai.review import (
    _is_stale as _is_stale,  # pyright: ignore[reportPrivateUsage]
)

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


HIGH_CONFIDENCE_RESPONSE = json.dumps(
    {
        "replacement": "Platform/Deployment.md",
        "confidence": "high",
        "evidence": "The new page covers the same six steps with updated tooling.",
    }
)

NULL_RESPONSE = "null"

LOW_CONFIDENCE_RESPONSE = json.dumps(
    {
        "replacement": "Platform/Deployment.md",
        "confidence": "low",
        "evidence": "Superficial similarity only.",
    }
)


# ---------------------------------------------------------------------------
# _parse_stale_response
# ---------------------------------------------------------------------------


class TestParseStaleResponse:
    def test_high_confidence_returns_finding(self) -> None:
        stale = Path("Tech/Old Deployment Runbook.md")
        newer = [Path("Platform/Deployment.md")]
        finding = _parse_stale_response(HIGH_CONFIDENCE_RESPONSE, stale, newer, "2021-06-15")
        assert finding is not None
        assert finding.confidence == "high"
        assert finding.stale_path == stale
        assert "Deployment.md" in str(finding.replacement_path)
        assert finding.last_updated == "2021-06-15"
        assert "six steps" in finding.evidence

    def test_null_string_returns_none(self) -> None:
        finding = _parse_stale_response(NULL_RESPONSE, Path("A.md"), [], "2020-01-01")
        assert finding is None

    def test_low_confidence_returns_none(self) -> None:
        finding = _parse_stale_response(
            LOW_CONFIDENCE_RESPONSE, Path("A.md"), [Path("B.md")], "2020-01-01"
        )
        assert finding is None

    def test_invalid_json_returns_none(self) -> None:
        finding = _parse_stale_response("bad json", Path("A.md"), [], "")
        assert finding is None

    def test_missing_confidence_field_returns_none(self) -> None:
        raw = json.dumps({"replacement": "B.md", "evidence": "something"})
        finding = _parse_stale_response(raw, Path("A.md"), [Path("B.md")], "")
        assert finding is None

    def test_non_dict_json_returns_none(self) -> None:
        finding = _parse_stale_response("[1, 2, 3]", Path("A.md"), [], "")
        assert finding is None

    def test_missing_replacement_returns_none(self) -> None:
        raw = json.dumps({"confidence": "high", "evidence": "something"})
        finding = _parse_stale_response(raw, Path("A.md"), [Path("B.md")], "")
        assert finding is None


# ---------------------------------------------------------------------------
# judge_stale_candidate
# ---------------------------------------------------------------------------


class TestJudgeStaleCandidiate:
    def test_high_confidence_returns_finding(self) -> None:
        mock = _make_mock_client(HIGH_CONFIDENCE_RESPONSE)
        finding = judge_stale_candidate(
            Path("Tech/Old.md"),
            "Old content",
            "2021-06-15",
            [(Path("Platform/Deployment.md"), "New content")],
            client=mock,
            stale_hash=b"stale_hash",
        )
        assert finding is not None
        assert finding.confidence == "high"

    def test_null_response_returns_none(self) -> None:
        mock = _make_mock_client(NULL_RESPONSE)
        finding = judge_stale_candidate(
            Path("A.md"),
            "Content",
            "2020-01-01",
            [(Path("B.md"), "Newer content")],
            client=mock,
            stale_hash=b"hash",
        )
        assert finding is None

    def test_cache_key_includes_stale_hash(self) -> None:
        """Different stale file hashes produce different cache_key_extra."""
        mock = _make_mock_client(NULL_RESPONSE)

        judge_stale_candidate(
            Path("A.md"),
            "body",
            "2020-01-01",
            [(Path("B.md"), "newer")],
            client=mock,
            stale_hash=b"hash_1",
        )
        extra_1 = mock.chat.call_args.kwargs.get("cache_key_extra")

        judge_stale_candidate(
            Path("A.md"),
            "body",
            "2020-01-01",
            [(Path("B.md"), "newer")],
            client=mock,
            stale_hash=b"hash_2",
        )
        extra_2 = mock.chat.call_args.kwargs.get("cache_key_extra")

        assert extra_1 != extra_2

    def test_cache_key_includes_newer_hashes(self) -> None:
        """Different newer file content produces different cache_key_extra."""
        mock = _make_mock_client(NULL_RESPONSE)

        judge_stale_candidate(
            Path("A.md"),
            "body",
            "2020-01-01",
            [(Path("B.md"), "newer content A")],
            client=mock,
            stale_hash=b"hash",
        )
        extra_1 = mock.chat.call_args.kwargs.get("cache_key_extra")

        judge_stale_candidate(
            Path("A.md"),
            "body",
            "2020-01-01",
            [(Path("B.md"), "newer content B")],
            client=mock,
            stale_hash=b"hash",
        )
        extra_2 = mock.chat.call_args.kwargs.get("cache_key_extra")

        assert extra_1 != extra_2

    def test_prompt_includes_stale_path_and_newer(self) -> None:
        mock = _make_mock_client(NULL_RESPONSE)
        judge_stale_candidate(
            Path("Tech/Old.md"),
            "old content",
            "2021-06-15",
            [(Path("Platform/New.md"), "new content")],
            client=mock,
            stale_hash=b"h",
        )
        user_msg = mock.chat.call_args.kwargs.get("user", "")
        assert "Tech/Old.md" in user_msg
        assert "Platform/New.md" in user_msg


# ---------------------------------------------------------------------------
# _is_stale helper
# ---------------------------------------------------------------------------


class TestIsStale:
    def test_old_updated_at_is_stale(self) -> None:
        from datetime import UTC, datetime

        content = "---\nupdated_at: '2021-01-01'\n---\n\nBody"
        fm = {"updated_at": "2021-01-01"}
        now = datetime(2026, 5, 8, tzinfo=UTC)
        stale, date_str = _is_stale(content, fm, now, 365)
        assert stale is True
        assert date_str == "2021-01-01"

    def test_recent_updated_at_not_stale(self) -> None:
        from datetime import UTC, datetime

        content = "---\nupdated_at: '2026-04-01'\n---\n\nBody"
        fm = {"updated_at": "2026-04-01"}
        now = datetime(2026, 5, 8, tzinfo=UTC)
        stale, _ = _is_stale(content, fm, now, 365)
        assert stale is False

    def test_no_date_not_stale(self) -> None:
        from datetime import UTC, datetime

        content = "No date anywhere"
        fm: dict[str, str] = {}
        now = datetime(2026, 5, 8, tzinfo=UTC)
        stale, _ = _is_stale(content, fm, now, 365)
        assert stale is False


# ---------------------------------------------------------------------------
# run_review integration (mocked client)
# ---------------------------------------------------------------------------


class TestRunReview:
    FIXTURES = Path(__file__).parent / "fixtures" / "review"

    def _make_client(self, response: str = NULL_RESPONSE) -> MagicMock:
        mock = MagicMock()
        mock.chat.return_value = _make_chat_result(response)
        mock.summary.api_calls = 0
        mock.summary.cached_calls = 0
        return mock

    def test_duplicates_produces_report_file(self, tmp_path: Path) -> None:
        cfg = ReviewConfig(
            directory=self.FIXTURES,
            modes={"duplicates"},
            top_k=3,
            similarity=0.0,  # low threshold to get some pairs through BM25
            output_path=tmp_path / "report.md",
        )
        report_path = run_review(cfg, self._make_client())
        assert report_path.exists()
        content = report_path.read_text()
        assert "## Likely duplicates" in content

    def test_stale_produces_report_file(self, tmp_path: Path) -> None:
        cfg = ReviewConfig(
            directory=self.FIXTURES,
            modes={"stale"},
            age_days=365,
            output_path=tmp_path / "stale-report.md",
        )
        report_path = run_review(cfg, self._make_client())
        assert report_path.exists()
        content = report_path.read_text()
        assert "## Stale content" in content

    def test_inconsistencies_produces_report_file(self, tmp_path: Path) -> None:
        cfg = ReviewConfig(
            directory=self.FIXTURES,
            modes={"inconsistencies"},
            top_k=3,
            output_path=tmp_path / "incon-report.md",
        )
        report_path = run_review(cfg, self._make_client())
        assert report_path.exists()
        content = report_path.read_text()
        assert "## Possible inconsistencies" in content

    def test_all_mode_runs_three_sections(self, tmp_path: Path) -> None:
        cfg = ReviewConfig(
            directory=self.FIXTURES,
            modes={"duplicates", "inconsistencies", "stale"},
            top_k=3,
            similarity=0.0,
            output_path=tmp_path / "all-report.md",
        )
        report_path = run_review(cfg, self._make_client())
        content = report_path.read_text()
        assert "## Likely duplicates" in content
        assert "## Possible inconsistencies" in content
        assert "## Stale content" in content

    def test_all_mode_index_built_once(self, tmp_path: Path) -> None:
        """BM25 index is built once; results are consistent across modes."""
        from mdd.ai.bm25 import Bm25Index

        build_calls: list[int] = []
        original_build = Bm25Index.build

        @classmethod  # type: ignore[misc]
        def counting_build(cls: type, docs: list[tuple[Path, str]]) -> Bm25Index:
            build_calls.append(1)
            return original_build(docs)

        with patch.object(Bm25Index, "build", counting_build):
            cfg = ReviewConfig(
                directory=self.FIXTURES,
                modes={"duplicates", "inconsistencies", "stale"},
                top_k=3,
                similarity=0.0,
                output_path=tmp_path / "all-report.md",
            )
            run_review(cfg, self._make_client())

        assert len(build_calls) == 1, f"BM25 index was built {len(build_calls)} times (expected 1)"

    def test_output_dir_default_under_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        cfg = ReviewConfig(
            directory=self.FIXTURES,
            modes={"duplicates"},
            top_k=2,
            similarity=0.0,
        )
        report_path = run_review(cfg, self._make_client())
        assert str(report_path).startswith(str(tmp_path / "docs" / "review"))

    def test_collision_gets_numeric_suffix(self, tmp_path: Path) -> None:
        cfg = ReviewConfig(
            directory=self.FIXTURES,
            modes={"duplicates"},
            top_k=2,
            similarity=0.0,
            output_path=tmp_path / "report.md",
        )
        # First run writes report.md
        p1 = run_review(cfg, self._make_client())
        assert p1 == tmp_path / "report.md"

        # Second run with explicit output_path overwrites — spec says no overwrite for
        # auto-chosen paths; with explicit path it just uses that path.
        # Reset output_path to None to test auto-collision:
        cfg2 = ReviewConfig(
            directory=self.FIXTURES,
            modes={"duplicates"},
            top_k=2,
            similarity=0.0,
            output_dir=tmp_path,
        )
        p2 = run_review(cfg2, self._make_client())
        p3 = run_review(cfg2, self._make_client())
        assert p2 != p3
        assert "-2" in p3.name or "-3" in p3.name

    def test_empty_directory_produces_report(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "empty"
        docs_dir.mkdir()
        cfg = ReviewConfig(
            directory=docs_dir,
            modes={"duplicates"},
            output_path=tmp_path / "report.md",
        )
        report_path = run_review(cfg, self._make_client())
        assert report_path.exists()

    def test_nonexistent_directory_raises(self, tmp_path: Path) -> None:
        cfg = ReviewConfig(
            directory=tmp_path / "nonexistent",
            modes={"duplicates"},
            output_path=tmp_path / "report.md",
        )
        with pytest.raises(ValueError, match="Not a directory"):
            run_review(cfg, self._make_client())
