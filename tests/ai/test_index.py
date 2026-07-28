"""Tests for mdd.ai.index — INDEX.md generation with per-file summary caching (spec S21)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from mdd.ai.index import FileSummary, index_dir
from mdd.ai.index import _body_hash as _body_hash  # pyright: ignore[reportPrivateUsage]
from mdd.ai.index import (
    _cluster_summaries as _cluster_summaries,  # pyright: ignore[reportPrivateUsage]
)
from mdd.ai.index import (
    _collect_md_files as _collect_md_files,  # pyright: ignore[reportPrivateUsage]
)
from mdd.ai.index import _path_to_title as _path_to_title  # pyright: ignore[reportPrivateUsage]
from mdd.ai.index import _render_index as _render_index  # pyright: ignore[reportPrivateUsage]
from mdd.ai.models import ChatResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _make_chat_result(text: str, cached: bool = False) -> ChatResult:
    return ChatResult(
        text=text,
        cached=cached,
        prompt_tokens=8,
        completion_tokens=4,
        cost_usd=None,
    )


def _make_mock_client(summary_text: str = "A one-sentence summary.") -> MagicMock:
    mock = MagicMock()
    mock.chat.return_value = _make_chat_result(summary_text)
    mock._config.models = {"summarise": "claude-haiku-4-5", "default": "claude-sonnet-4-5"}
    mock.model_for_task.return_value = "claude-haiku-4-5"
    mock.summary.api_calls = 1
    mock.summary.prompt_tokens = 8
    mock.summary.completion_tokens = 4
    mock.summary.cost_usd = 0.0
    return mock


def _write_md(path: Path, body: str, frontmatter: dict[str, Any] | None = None) -> None:
    if frontmatter:
        fm_str = yaml.safe_dump(frontmatter, default_flow_style=False, sort_keys=False)
        path.write_text(f"---\n{fm_str}---\n{body}", encoding="utf-8")
    else:
        path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# _collect_md_files
# ---------------------------------------------------------------------------


class TestCollectMdFiles:
    def test_finds_md_files_recursively(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("A", encoding="utf-8")
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (subdir / "b.md").write_text("B", encoding="utf-8")

        files = _collect_md_files(tmp_path)
        names = [f.name for f in files]
        assert "a.md" in names
        assert "b.md" in names

    def test_excludes_index_md(self, tmp_path: Path) -> None:
        (tmp_path / "INDEX.md").write_text("Index", encoding="utf-8")
        (tmp_path / "page.md").write_text("Page", encoding="utf-8")

        files = _collect_md_files(tmp_path)
        names = [f.name for f in files]
        assert "INDEX.md" not in names
        assert "page.md" in names

    def test_returns_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "z.md").write_text("Z", encoding="utf-8")
        (tmp_path / "a.md").write_text("A", encoding="utf-8")
        (tmp_path / "m.md").write_text("M", encoding="utf-8")

        files = _collect_md_files(tmp_path)
        names = [f.name for f in files]
        assert names == sorted(names)

    def test_empty_dir(self, tmp_path: Path) -> None:
        files = _collect_md_files(tmp_path)
        assert files == []

    def test_no_md_files(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("not md", encoding="utf-8")
        files = _collect_md_files(tmp_path)
        assert files == []


# ---------------------------------------------------------------------------
# _body_hash
# ---------------------------------------------------------------------------


class TestBodyHash:
    def test_same_content_same_hash(self) -> None:
        assert _body_hash("hello") == _body_hash("hello")

    def test_different_content_different_hash(self) -> None:
        assert _body_hash("hello") != _body_hash("world")

    def test_returns_hex_string(self) -> None:
        h = _body_hash("test")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# _path_to_title
# ---------------------------------------------------------------------------


class TestPathToTitle:
    def test_simple_stem(self) -> None:
        assert _path_to_title("Architecture.md") == "Architecture"

    def test_hyphenated(self) -> None:
        assert _path_to_title("Platform-Topology.md") == "Platform Topology"

    def test_underscored(self) -> None:
        assert _path_to_title("my_document.md") == "my document"

    def test_nested_path(self) -> None:
        assert _path_to_title("Architecture/Platform-Topology.md") == "Platform Topology"


# ---------------------------------------------------------------------------
# _render_index
# ---------------------------------------------------------------------------


class TestRenderIndex:
    def _make_summaries(self, paths: list[str]) -> list[FileSummary]:
        return [
            FileSummary(
                path=Path(p),
                rel_path=p,
                summary=f"Summary of {p}.",
                cached=True,
            )
            for p in paths
        ]

    def test_flat_list_depth_1(self) -> None:
        summaries = self._make_summaries(["a.md", "b.md"])
        content = _render_index(summaries, clusters=None, generated_at="2026-01-01T00:00:00Z")

        # Must have frontmatter
        assert "ai_generated: true" in content
        assert "generated_by: mdd ai index" in content

        # Must have title and caveat
        assert "# Index" in content
        assert "Auto-generated" in content

        # Must list files
        assert "[a](" in content or "[A](" in content
        assert "Summary of a.md" in content
        assert "Summary of b.md" in content

        # No H2 sections (flat)
        assert "## " not in content

    def test_clustered_depth_all(self) -> None:
        summaries = self._make_summaries(["Architecture/Topology.md", "Process/Onboarding.md"])
        clusters: list[dict[str, Any]] = [
            {"topic_title": "Architecture", "file_paths": ["Architecture/Topology.md"]},
            {"topic_title": "Process", "file_paths": ["Process/Onboarding.md"]},
        ]
        content = _render_index(summaries, clusters=clusters, generated_at="2026-01-01T00:00:00Z")

        assert "## Architecture" in content
        assert "## Process" in content

    def test_unclaimed_files_go_to_other(self) -> None:
        summaries = self._make_summaries(["a.md", "b.md", "c.md"])
        clusters: list[dict[str, Any]] = [
            {"topic_title": "Group1", "file_paths": ["a.md"]},
        ]
        content = _render_index(summaries, clusters=clusters, generated_at="2026-01-01T00:00:00Z")

        assert "## Other" in content
        assert "b.md" in content or "[b]" in content
        assert "c.md" in content or "[c]" in content

    def test_frontmatter_is_valid_yaml(self) -> None:
        summaries = self._make_summaries(["a.md"])
        content = _render_index(summaries, clusters=None, generated_at="2026-01-01T00:00:00Z")

        # Strip the body after frontmatter for YAML parsing.
        assert content.startswith("---\n")
        rest = content[4:]
        end = rest.find("\n---\n")
        assert end != -1
        fm_yaml = rest[:end]
        fm = yaml.safe_load(fm_yaml)
        assert fm["ai_generated"] is True
        assert fm["generated_by"] == "mdd ai index"


# ---------------------------------------------------------------------------
# _cluster_summaries
# ---------------------------------------------------------------------------


class TestClusterSummaries:
    def test_returns_clusters_from_model(self, tmp_path: Path) -> None:
        summaries = [
            FileSummary(Path("a.md"), "a.md", "Summary A.", False),
            FileSummary(Path("b.md"), "b.md", "Summary B.", False),
        ]
        cluster_response = json.dumps([{"topic_title": "Group", "file_paths": ["a.md", "b.md"]}])
        mock_client = MagicMock()
        mock_client.chat.return_value = _make_chat_result(cluster_response)
        mock_client._config.models = {"default": "claude-sonnet-4-5"}

        result = _cluster_summaries(summaries, mock_client, model=None)  # pyright: ignore[reportArgumentType]

        assert len(result) == 1
        assert result[0]["topic_title"] == "Group"

    def test_fallback_on_json_parse_error(self) -> None:
        summaries = [
            FileSummary(Path("a.md"), "a.md", "Summary A.", False),
        ]
        mock_client = MagicMock()
        mock_client.chat.return_value = _make_chat_result("this is not json")
        mock_client._config.models = {"default": "claude-sonnet-4-5"}

        result = _cluster_summaries(summaries, mock_client, model=None)  # pyright: ignore[reportArgumentType]

        assert len(result) == 1
        assert result[0]["topic_title"] == "Pages"
        assert "a.md" in result[0]["file_paths"]

    def test_fallback_on_client_error(self) -> None:
        summaries = [
            FileSummary(Path("a.md"), "a.md", "Summary A.", False),
        ]
        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("network down")
        mock_client._config.models = {"default": "claude-sonnet-4-5"}

        result = _cluster_summaries(summaries, mock_client, model=None)  # pyright: ignore[reportArgumentType]

        # Falls back gracefully
        assert len(result) == 1
        assert "a.md" in result[0]["file_paths"]

    def test_strips_markdown_fences_from_json_response(self) -> None:
        summaries = [FileSummary(Path("a.md"), "a.md", "Summary.", False)]
        clusters = [{"topic_title": "T", "file_paths": ["a.md"]}]
        fenced_response = f"```json\n{json.dumps(clusters)}\n```"

        mock_client = MagicMock()
        mock_client.chat.return_value = _make_chat_result(fenced_response)
        mock_client._config.models = {"default": "claude-sonnet-4-5"}

        result = _cluster_summaries(summaries, mock_client, model=None)  # pyright: ignore[reportArgumentType]
        assert result[0]["topic_title"] == "T"


# ---------------------------------------------------------------------------
# index_dir — happy path and edge cases
# ---------------------------------------------------------------------------


class TestIndexDir:
    def test_empty_dir_returns_ok(self, tmp_path: Path) -> None:
        mock_client = _make_mock_client()
        result = index_dir(tmp_path, mock_client)  # pyright: ignore[reportArgumentType]
        assert result.status == "ok"
        assert result.files_total == 0

    def test_not_a_directory_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x", encoding="utf-8")
        mock_client = _make_mock_client()
        result = index_dir(f, mock_client)  # pyright: ignore[reportArgumentType]
        assert result.status == "error"

    def test_generates_index_without_apply(self, tmp_path: Path, capsys: Any) -> None:
        _write_md(tmp_path / "a.md", "Content A.")

        mock_client = _make_mock_client("A summary sentence.")
        result = index_dir(tmp_path, mock_client)  # pyright: ignore[reportArgumentType]

        assert result.status == "ok"
        assert result.files_total == 1
        # Without --apply, prints to stdout
        captured = capsys.readouterr()
        assert "# Index" in captured.out
        assert not (tmp_path / "INDEX.md").exists()

    def test_apply_writes_index_file(self, tmp_path: Path) -> None:
        _write_md(tmp_path / "a.md", "Content A.")
        _write_md(tmp_path / "b.md", "Content B.")

        mock_client = _make_mock_client("A one-sentence summary.")
        result = index_dir(tmp_path, mock_client, apply=True)  # pyright: ignore[reportArgumentType]

        assert result.status == "ok"
        assert (tmp_path / "INDEX.md").exists()
        content = (tmp_path / "INDEX.md").read_text()
        assert "# Index" in content
        assert "ai_generated: true" in content

    def test_cached_summary_skips_api_call(self, tmp_path: Path) -> None:
        """Files whose frontmatter hash matches must not call the API."""
        body = "Content of the document.\n"
        current_hash = _body_hash(body)
        fm: dict[str, Any] = {
            "mdd": {"ai": {"summary": "Cached summary.", "summary_input_hash": current_hash}}
        }
        _write_md(tmp_path / "page.md", body, frontmatter=fm)

        call_count = 0

        def counting_chat(**kwargs: Any) -> ChatResult:  # pyright: ignore[reportAny]
            nonlocal call_count
            call_count += 1
            return _make_chat_result("Fresh summary.")

        mock_client = MagicMock()
        mock_client.chat.side_effect = counting_chat
        mock_client._config.models = {"summarise": "claude-haiku-4-5"}
        mock_client.summary.api_calls = 0
        mock_client.summary.prompt_tokens = 0
        mock_client.summary.completion_tokens = 0
        mock_client.summary.cost_usd = 0.0

        result = index_dir(tmp_path, mock_client)  # pyright: ignore[reportArgumentType]

        assert result.status == "ok"
        assert call_count == 0
        assert result.summaries_cached == 1

    def test_stale_hash_triggers_new_api_call(self, tmp_path: Path) -> None:
        """When body changes, the cached summary must be ignored."""
        body = "Updated content.\n"
        fm: dict[str, Any] = {
            "mdd": {
                "ai": {
                    "summary": "Old summary.",
                    "summary_input_hash": "stale_hash_xxxx",  # not matching current body
                }
            }
        }
        _write_md(tmp_path / "page.md", body, frontmatter=fm)

        mock_client = _make_mock_client("Fresh summary.")

        result = index_dir(tmp_path, mock_client)  # pyright: ignore[reportArgumentType]

        assert result.status == "ok"
        assert result.summaries_computed == 1
        assert result.summaries_cached == 0

    def test_apply_writes_summary_to_frontmatter(self, tmp_path: Path) -> None:
        """With --apply, summary must be written back into the source file's frontmatter."""
        body = "Some document content.\n"
        src = tmp_path / "page.md"
        src.write_text(body, encoding="utf-8")

        mock_client = _make_mock_client("This describes the document content.")

        index_dir(tmp_path, mock_client, apply=True)  # pyright: ignore[reportArgumentType]

        content = src.read_text()
        assert "summary:" in content
        assert "summary_input_hash:" in content

    def test_depth_all_triggers_cluster_call(self, tmp_path: Path) -> None:
        _write_md(tmp_path / "a.md", "Content A.")
        _write_md(tmp_path / "b.md", "Content B.")

        cluster_response = json.dumps(
            [{"topic_title": "All Pages", "file_paths": ["a.md", "b.md"]}]
        )

        call_tasks: list[str] = []

        def tracking_chat(**kwargs: Any) -> ChatResult:  # pyright: ignore[reportAny]
            call_tasks.append(kwargs.get("task", ""))
            if kwargs.get("task") == "default":
                return _make_chat_result(cluster_response)
            return _make_chat_result("A summary.")

        mock_client = MagicMock()
        mock_client.chat.side_effect = tracking_chat
        mock_client._config.models = {
            "summarise": "claude-haiku-4-5",
            "default": "claude-sonnet-4-5",
        }
        mock_client.model_for_task.return_value = "claude-haiku-4-5"
        mock_client.summary.api_calls = 3
        mock_client.summary.prompt_tokens = 24
        mock_client.summary.completion_tokens = 12
        mock_client.summary.cost_usd = 0.0

        result = index_dir(tmp_path, mock_client, depth="all", apply=True)  # pyright: ignore[reportArgumentType]

        assert result.status == "ok"
        # Cluster call should have happened (task="default" for clustering)
        assert "default" in call_tasks

        index_content = (tmp_path / "INDEX.md").read_text()
        assert "## All Pages" in index_content

    def test_depth_1_no_cluster_call(self, tmp_path: Path) -> None:
        _write_md(tmp_path / "a.md", "Content.")
        mock_client = _make_mock_client("Summary.")

        result = index_dir(tmp_path, mock_client, depth="1", apply=True)  # pyright: ignore[reportArgumentType]

        assert result.status == "ok"
        index_content = (tmp_path / "INDEX.md").read_text()
        assert "## " not in index_content  # no H2 sections

    def test_error_in_one_file_continues(self, tmp_path: Path) -> None:
        """If one file fails summarisation, others should still succeed."""
        _write_md(tmp_path / "a.md", "Content A.")
        _write_md(tmp_path / "b.md", "Content B.")

        call_n = 0

        def failing_on_b(**kwargs: Any) -> ChatResult:  # pyright: ignore[reportAny]
            nonlocal call_n
            call_n += 1
            if call_n == 1:
                return _make_chat_result("Summary A.")
            raise RuntimeError("API error on file B")

        mock_client = MagicMock()
        mock_client.chat.side_effect = failing_on_b
        mock_client._config.models = {"summarise": "claude-haiku-4-5"}
        mock_client.summary.api_calls = 1
        mock_client.summary.prompt_tokens = 8
        mock_client.summary.completion_tokens = 4
        mock_client.summary.cost_usd = 0.0

        result = index_dir(tmp_path, mock_client)  # pyright: ignore[reportArgumentType]

        assert result.status == "ok"
        assert result.errors == 1


# ---------------------------------------------------------------------------
# Integration test (skipped unless MDD_AI_TEST=1)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestIndexIntegration:
    def test_live_index(self, tmp_path: Path) -> None:
        from mdd.ai.client import Client

        (tmp_path / "a.md").write_text(
            "# Architecture\n\nDescribes the platform topology.\n", encoding="utf-8"
        )
        (tmp_path / "b.md").write_text(
            "# Process\n\nDescribes the onboarding process.\n", encoding="utf-8"
        )

        client = Client()
        result = index_dir(tmp_path, client, apply=True)

        assert result.status == "ok"
        assert (tmp_path / "INDEX.md").exists()
        assert result.files_total == 2
