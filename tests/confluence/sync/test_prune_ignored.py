"""Tests for the spec S39 ``--prune-ignored`` wiring in ``mdd confluence sync-space``.

P04 MR 2 — Confluence side of issue #120. Mirrors the sharepoint test set
in ``tests/sharepoint/test_bidirectional_sync.py::TestSyncFolderPruneIgnored``.
"""

from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from mdd.confluence.config import ConfluenceConfig
from mdd.confluence.sync import SyncOptions, sync_space
from mdd.utils.mddignore import MddIgnore

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=str(path), check=True, capture_output=True
    )


def _git_commit(path: Path, msg: str = "init") -> None:
    subprocess.run(["git", "add", "-A"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", msg, "--allow-empty"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )


def _write_ignore(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_config() -> ConfluenceConfig:
    return ConfluenceConfig(
        url="https://example.atlassian.net",
        username="test",
        api_token="token",
    )


def _make_get_side_effect(data: dict[str, Any]) -> Any:  # pyright: ignore[reportAny]
    def _get(path: str, **kwargs: Any) -> dict[str, Any]:  # pyright: ignore[reportAny]
        if "spaces" in path:
            return {"results": [{"id": data["space_id"], "key": "TEST"}], "_links": {}}
        if "pages" in path:
            return {"results": data["pages"], "_links": {}}
        return {"results": [], "_links": {}}

    return _get


class TestSyncSpacePruneIgnored:
    """``--prune-ignored`` deletes already-synced files matching the matcher."""

    def test_prune_removes_matched_files_and_logs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _write_ignore(output_dir / ".mddignore", "Archive/", "*.tmp")
        _git_commit(output_dir, "add ignore")
        matcher = MddIgnore.load(output_dir)
        # Two already-synced files that newly match the matcher.
        stale_dir = output_dir / "Archive"
        stale_dir.mkdir()
        stale_file = stale_dir / "Old.md"
        stale_file.write_text("# old", encoding="utf-8")
        scratch = output_dir / "scratch.tmp"
        scratch.write_text("scratch", encoding="utf-8")
        # And one file that the matcher does NOT touch.
        keep = output_dir / "Live.md"
        keep.write_text("# live", encoding="utf-8")

        mock_client = MagicMock()
        mock_client.get.side_effect = _make_get_side_effect({"space_id": "98306", "pages": []})
        mock_client.get_folder.side_effect = Exception("no folders")

        with (
            caplog.at_level(logging.INFO, logger="mdd"),
            patch("mdd.confluence.sync.is_dirty", return_value=False),
            patch("mdd.confluence.sync.get_space_id", return_value="98306"),
            patch("mdd.confluence.sync.state.list_pages_for_sync") as mock_list,
        ):
            mock_list.return_value = []
            summary = sync_space(
                mock_client,
                "TEST",
                output_dir,
                _make_config(),
                opts=SyncOptions(matcher=matcher, prune_ignored=True),
            )

        # Both matched files are gone, the unmatched one is left alone.
        assert not stale_file.exists()
        assert not scratch.exists()
        assert keep.exists()
        # Summary counters reflect the prune pass.
        assert summary.pruned_ignored == 2
        assert summary.pruned_ignored_dry_run is False
        assert sorted(summary.pruned_ignored_paths) == ["Archive/Old.md", "scratch.tmp"]
        # One INFO line per deletion.
        assert "pruned (ignored): scratch.tmp" in caplog.text
        assert "pruned (ignored): Archive/Old.md" in caplog.text

    def test_prune_dry_run_does_not_delete(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _write_ignore(output_dir / ".mddignore", "*.tmp")
        _git_commit(output_dir, "add ignore")
        matcher = MddIgnore.load(output_dir)
        stale = output_dir / "scratch.tmp"
        stale.write_text("scratch", encoding="utf-8")

        mock_client = MagicMock()
        mock_client.get_folder.side_effect = Exception("no folders")

        with (
            caplog.at_level(logging.INFO, logger="mdd"),
            patch("mdd.confluence.sync.is_dirty", return_value=False),
            patch("mdd.confluence.sync.get_space_id", return_value="98306"),
            patch("mdd.confluence.sync.state.list_pages_for_sync") as mock_list,
        ):
            mock_list.return_value = []
            summary = sync_space(
                mock_client,
                "TEST",
                output_dir,
                _make_config(),
                opts=SyncOptions(matcher=matcher, prune_ignored=True, dry_run=True),
            )

        # File is still on disk.
        assert stale.exists()
        assert summary.pruned_ignored == 1
        assert summary.pruned_ignored_dry_run is True
        assert summary.pruned_ignored_paths == ["scratch.tmp"]
        # ``would prune`` log line was emitted.
        assert "would prune (ignored, dry-run): scratch.tmp" in caplog.text

    def test_no_prune_flag_leaves_files_alone(self, tmp_path: Path) -> None:
        # Regression guard: the default-off contract — passing a matcher
        # without ``--prune-ignored`` must not delete already-synced files.
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _write_ignore(output_dir / ".mddignore", "*.tmp")
        _git_commit(output_dir, "add ignore")
        matcher = MddIgnore.load(output_dir)
        stale = output_dir / "scratch.tmp"
        stale.write_text("scratch", encoding="utf-8")

        mock_client = MagicMock()
        mock_client.get_folder.side_effect = Exception("no folders")

        with (
            patch("mdd.confluence.sync.is_dirty", return_value=False),
            patch("mdd.confluence.sync.get_space_id", return_value="98306"),
            patch("mdd.confluence.sync.state.list_pages_for_sync") as mock_list,
        ):
            mock_list.return_value = []
            summary = sync_space(
                mock_client,
                "TEST",
                output_dir,
                _make_config(),
                opts=SyncOptions(matcher=matcher),
            )

        assert stale.exists()
        assert summary.pruned_ignored == 0
        assert summary.pruned_ignored_dry_run is False

    def test_prune_without_matcher_is_noop(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _git_commit(output_dir, "init")
        # No matcher, no .mddignore — flag set, but nothing to prune.
        keep = output_dir / "keep.md"
        keep.write_text("keep", encoding="utf-8")

        mock_client = MagicMock()
        mock_client.get_folder.side_effect = Exception("no folders")

        with (
            patch("mdd.confluence.sync.is_dirty", return_value=False),
            patch("mdd.confluence.sync.get_space_id", return_value="98306"),
            patch("mdd.confluence.sync.state.list_pages_for_sync") as mock_list,
        ):
            mock_list.return_value = []
            summary = sync_space(
                mock_client,
                "TEST",
                output_dir,
                _make_config(),
                opts=SyncOptions(prune_ignored=True),
            )

        assert keep.exists()
        assert summary.pruned_ignored == 0
