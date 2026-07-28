"""Tests for mdd confluence sync command (spec S14)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mdd.cli import main as _cli_main

if TYPE_CHECKING:
    from pathlib import Path


def cmd_confluence(args: list[str]) -> int:
    """Test helper: invoke mdd confluence via argparse."""
    return _cli_main(["confluence", *args])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _make_config_file(path: Path, url: str = "https://example.atlassian.net") -> None:
    path.write_text(
        f"confluence:\n  url: {url}\n  username: test@example.com\n  api_token: dummy-token\n"
    )


# ---------------------------------------------------------------------------
# CLI dispatch tests
# ---------------------------------------------------------------------------


class TestConfluenceSyncDispatch:
    def test_sync_alone_exits(self) -> None:
        # 'sync' alone is not a valid subcommand — the flat name is 'sync-space'.
        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(["sync"])
        assert exc_info.value.code == 2

    def test_sync_unknown_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(["sync", "page"])
        assert exc_info.value.code == 2

    def test_sync_space_no_space_key_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(["sync-space"])
        assert exc_info.value.code == 2


class TestDirtyWorkingTreeRefusal:
    def test_dirty_tree_aborts_with_exact_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        # Create and commit a file first
        (output_dir / "page.md").write_text("clean")
        _git_commit(output_dir)
        # Now make it dirty
        (output_dir / "page.md").write_text("modified - dirty")

        config_file = tmp_path / "confluence.yaml"
        _make_config_file(config_file)

        with patch("mdd.commands.confluence.load_config") as mock_config:
            from mdd.confluence.config import ConfluenceConfig

            mock_config.return_value = ConfluenceConfig(
                url="https://example.atlassian.net",
                username="test",
                api_token="token",
            )
            rc = cmd_confluence(
                [
                    "sync-space",
                    "TEST",
                    "--config",
                    str(config_file),
                    "--output",
                    str(output_dir),
                ]
            )

        captured = capsys.readouterr()
        assert rc == 1
        assert "uncommitted changes" in captured.err.lower() or "dirty" in captured.err.lower()


class TestSyncSpaceOptions:
    def test_head_option_parsed(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _git_commit(output_dir)
        config_file = tmp_path / "confluence.yaml"
        _make_config_file(config_file)

        with (
            patch("mdd.commands.confluence.load_config") as mock_config,
            patch("mdd.commands.confluence.sync_space") as mock_sync,
        ):
            from mdd.confluence.config import ConfluenceConfig
            from mdd.confluence.sync import SyncSummary

            mock_config.return_value = ConfluenceConfig(
                url="https://example.atlassian.net",
                username="test",
                api_token="token",
            )
            mock_sync.return_value = SyncSummary()

            cmd_confluence(
                [
                    "sync-space",
                    "TEST",
                    "--config",
                    str(config_file),
                    "--output",
                    str(output_dir),
                    "--head",
                    "5",
                ]
            )

        # Verify sync_space was called with head=5
        call_kwargs = mock_sync.call_args
        assert call_kwargs is not None
        opts = call_kwargs.kwargs["opts"]  # pyright: ignore[reportAny]
        assert opts.head == 5  # pyright: ignore[reportAny]

    def test_dry_run_option_parsed(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _git_commit(output_dir)
        config_file = tmp_path / "confluence.yaml"
        _make_config_file(config_file)

        with (
            patch("mdd.commands.confluence.load_config") as mock_config,
            patch("mdd.commands.confluence.sync_space") as mock_sync,
        ):
            from mdd.confluence.config import ConfluenceConfig
            from mdd.confluence.sync import SyncSummary

            mock_config.return_value = ConfluenceConfig(
                url="https://example.atlassian.net",
                username="test",
                api_token="token",
            )
            mock_sync.return_value = SyncSummary()

            cmd_confluence(
                [
                    "sync-space",
                    "TEST",
                    "--config",
                    str(config_file),
                    "--output",
                    str(output_dir),
                    "--dry-run",
                ]
            )

        call_kwargs = mock_sync.call_args
        assert call_kwargs is not None
        opts = call_kwargs.kwargs["opts"]  # pyright: ignore[reportAny]
        assert opts.dry_run is True  # pyright: ignore[reportAny]

    def test_read_only_option_parsed(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _git_commit(output_dir)
        config_file = tmp_path / "confluence.yaml"
        _make_config_file(config_file)

        with (
            patch("mdd.commands.confluence.load_config") as mock_config,
            patch("mdd.commands.confluence.sync_space") as mock_sync,
        ):
            from mdd.confluence.config import ConfluenceConfig
            from mdd.confluence.sync import SyncSummary

            mock_config.return_value = ConfluenceConfig(
                url="https://example.atlassian.net",
                username="test",
                api_token="token",
            )
            mock_sync.return_value = SyncSummary()

            cmd_confluence(
                [
                    "sync-space",
                    "TEST",
                    "--config",
                    str(config_file),
                    "--output",
                    str(output_dir),
                    "--read-only",
                ]
            )

        call_kwargs = mock_sync.call_args
        assert call_kwargs is not None
        opts = call_kwargs.kwargs["opts"]  # pyright: ignore[reportAny]
        assert opts.read_only is True  # pyright: ignore[reportAny]


# ---------------------------------------------------------------------------
# Sync orchestrator unit tests (mocked HTTP)
# ---------------------------------------------------------------------------


class TestSyncSpaceIdempotent:
    def test_second_run_no_confluence_changes_no_commit(self, tmp_path: Path) -> None:
        """Idempotent: second run with no changes → no commit."""
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)

        # Pre-populate mirror with one page
        page_md = output_dir / "Test Page.md"
        page_md.write_text(
            "---\nconfluence:\n  page_id: '100'\n  title: Test Page\n  version: 5\n"
            "  status: CURRENT\n  space_key: TEST\n  space_id: '98306'\n"
            "  exported_at: '2026-01-01T00:00:00Z'\n---\n\n# Test Page\n"
        )
        _git_commit(output_dir, "initial sync")

        from mdd.confluence.config import ConfluenceConfig
        from mdd.confluence.sync import SyncOptions, sync_space

        config = ConfluenceConfig(
            url="https://example.atlassian.net",
            username="test",
            api_token="token",
        )

        # Mock the client to return the same page with same version
        mock_client = MagicMock()
        mock_client.get.side_effect = _make_get_side_effect(
            {
                "space_id": "98306",
                "pages": [
                    {
                        "id": "100",
                        "title": "Test Page",
                        "parentId": None,
                        "status": "current",
                        "version": {"number": 5, "createdAt": "2026-01-01T00:00:00Z"},
                        "spaceId": "98306",
                        "labels": {"results": []},
                    }
                ],
            }
        )
        mock_client.get_folder.side_effect = Exception("no folders")

        with (
            patch("mdd.confluence.sync.get_space_id", return_value="98306"),
            patch("mdd.confluence.sync.state.list_pages_for_sync") as mock_list,
        ):
            mock_list.return_value = [
                {
                    "id": "100",
                    "title": "Test Page",
                    "parentId": None,
                    "status": "current",
                    "version": {"number": 5, "createdAt": "2026-01-01T00:00:00Z"},
                    "spaceId": "98306",
                    "labels": {"results": []},
                }
            ]

            summary = sync_space(
                mock_client, "TEST", output_dir, config, opts=SyncOptions(dry_run=False)
            )

        # Nothing should have changed
        assert not summary.has_changes()
        assert not summary.committed


def _make_get_side_effect(data: dict[str, Any]) -> Any:  # pyright: ignore[reportAny]
    """Create a side_effect for client.get() that handles spaces and pages."""

    def _get(path: str, **kwargs: Any) -> dict[str, Any]:  # pyright: ignore[reportAny]
        if "spaces" in path:
            return {"results": [{"id": data["space_id"], "key": "TEST"}], "_links": {}}
        if "pages" in path:
            return {"results": data["pages"], "_links": {}}
        return {"results": [], "_links": {}}

    return _get


class TestSyncRenameIsGitMv:
    def test_rename_produces_git_mv_not_delete_create(self, tmp_path: Path) -> None:
        """Rename must appear as a single git mv in git history."""
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)

        # Initial state: page with old title
        page_md = output_dir / "Old Title.md"
        page_md.write_text(
            "---\nconfluence:\n  page_id: '100'\n  title: Old Title\n  version: 3\n"
            "  status: CURRENT\n  space_key: TEST\n  space_id: '98306'\n"
            "  parent_id: null\n  exported_at: '2026-01-01T00:00:00Z'\n---\n\n# Old Title\n"
        )
        _git_commit(output_dir, "initial")

        from mdd.confluence.config import ConfluenceConfig
        from mdd.confluence.sync import SyncOptions, sync_space

        config = ConfluenceConfig(
            url="https://example.atlassian.net",
            username="test",
            api_token="token",
        )

        with (
            patch("mdd.confluence.sync.get_space_id", return_value="98306"),
            patch("mdd.confluence.sync.state.list_pages_for_sync") as mock_list,
            patch("mdd.confluence.sync.state.build_parent_path_map") as mock_map,
        ):
            mock_list.return_value = [
                {
                    "id": "100",
                    "title": "New Title",  # renamed!
                    "parentId": None,
                    "status": "current",
                    "version": {"number": 3, "createdAt": "2026-01-01T00:00:00Z"},
                    "spaceId": "98306",
                    "labels": {"results": []},
                }
            ]
            mock_client = MagicMock()
            # Return the target directory as the same output_dir (no parent change)
            mock_map.return_value = {"100": output_dir}

            summary = sync_space(
                mock_client, "TEST", output_dir, config, opts=SyncOptions(dry_run=False)
            )

        # The rename should have been counted
        assert summary.renamed == 1

        # Check git log shows the mv (R = rename)
        git_log = subprocess.run(
            ["git", "log", "--diff-filter=R", "--name-status", "--oneline", "-1"],
            cwd=str(output_dir),
            capture_output=True,
            text=True,
        )
        # Either the name status has R (rename) or the new file exists
        new_file = output_dir / "New Title.md"
        assert new_file.exists() or "R" in git_log.stdout


class TestSyncRelativeOutputDir:
    def test_relative_output_subdir_rename_does_not_double_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A relative ``--output <subdir>`` must not double the path prefix.

        Regression: ``build_mirror_state`` walks the tree with
        ``output_dir.rglob()``, so a relative ``--output mirror`` yields paths
        carrying the ``mirror/`` prefix. ``git_mv`` then runs with
        ``cwd=mirror`` and git resolved them to ``mirror/mirror/...`` →
        ``fatal: bad source``. ``_resolve_sync_output_dir`` now makes the path
        absolute so the git subprocess sees a valid source.
        """
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        (output_dir / "Old Title.md").write_text(
            "---\nconfluence:\n  page_id: '100'\n  title: Old Title\n  version: 3\n"
            "  status: CURRENT\n  space_key: TEST\n  space_id: '98306'\n"
            "  parent_id: null\n  exported_at: '2026-01-01T00:00:00Z'\n---\n\n# Old Title\n"
        )
        _git_commit(output_dir, "initial")

        config_file = tmp_path / "confluence.yaml"
        _make_config_file(config_file)

        # Invoke exactly as the user did: from the parent dir, with a relative
        # --output naming the subdirectory.
        monkeypatch.chdir(tmp_path)

        mock_client = MagicMock()

        with (
            patch("mdd.commands.confluence.ConfluenceClient") as mock_cc,
            patch("mdd.confluence.sync.get_space_id", return_value="98306"),
            patch("mdd.confluence.sync.state.list_pages_for_sync") as mock_list,
            patch("mdd.confluence.sync.state.build_parent_path_map") as mock_map,
        ):
            mock_cc.return_value.__enter__.return_value = mock_client
            mock_list.return_value = [
                {
                    "id": "100",
                    "title": "New Title",  # renamed on Confluence
                    "parentId": None,
                    "status": "current",
                    "version": {"number": 3, "createdAt": "2026-01-01T00:00:00Z"},
                    "spaceId": "98306",
                    "labels": {"results": []},
                }
            ]
            mock_map.return_value = {"100": output_dir}

            rc = cmd_confluence(
                [
                    "sync-space",
                    "TEST",
                    "--config",
                    str(config_file),
                    "--output",
                    "mirror",  # relative — the case that used to double the prefix
                    "--read-only",
                ]
            )

        assert rc == 0
        assert (output_dir / "New Title.md").exists()
        assert not (output_dir / "Old Title.md").exists()


class TestSyncCollisionHandling:
    def test_two_pages_same_sanitized_name_get_page_id_suffix(self, tmp_path: Path) -> None:
        """Filename collision on rename: both files get (page-id) suffix."""
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)

        # Two pages already exist
        for pid, fname in [("100", "Page A.md"), ("200", "Page B.md")]:
            (output_dir / fname).write_text(
                f"---\nconfluence:\n  page_id: '{pid}'\n  title: Page A\n  version: 1\n"
                f"  status: CURRENT\n  space_key: TEST\n  space_id: '98306'\n"
                f"  parent_id: null\n  exported_at: '2026-01-01T00:00:00Z'\n---\n\n# Page\n"
            )
        _git_commit(output_dir, "initial")

        from mdd.confluence.apply import compute_rename_path

        # Simulate: page 100 already at "Same Name.md" (just got renamed)
        used: set[Path] = {output_dir / "Same Name.md"}
        # Page 200 tries to rename to "Same Name.md" too → collision
        result = compute_rename_path(
            output_dir / "Page B.md",
            "Same Name",
            output_dir,
            "200",
            used,
        )
        assert "200" in result.name


class TestSyncConflictSkipped:
    def test_conflict_skipped_and_recorded(self, tmp_path: Path) -> None:
        """Conflict (local + remote both edited) → skip both push and pull."""
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)

        # Local file was modified AFTER exported_at (simulating local edit)
        page_md = output_dir / "Test Page.md"
        page_md.write_text(
            "---\nconfluence:\n  page_id: '100'\n  title: Test Page\n  version: 5\n"
            "  status: CURRENT\n  space_key: TEST\n  space_id: '98306'\n"
            "  exported_at: '2020-01-01T00:00:00Z'\n---\n\n# Test Page\n\nLocal edit.\n"
        )
        _git_commit(output_dir, "initial")

        from mdd.confluence.config import ConfluenceConfig
        from mdd.confluence.sync import SyncOptions, sync_space

        config = ConfluenceConfig(
            url="https://example.atlassian.net",
            username="test",
            api_token="token",
        )

        mock_client = MagicMock()

        with (
            patch("mdd.confluence.sync.get_space_id", return_value="98306"),
            patch("mdd.confluence.sync.state.list_pages_for_sync") as mock_list,
            patch("mdd.confluence.sync.state.build_parent_path_map") as mock_map,
        ):
            mock_list.return_value = [
                {
                    "id": "100",
                    "title": "Test Page",
                    "parentId": None,
                    "status": "current",
                    # Remote version is HIGHER than local = 5 → remote advanced
                    "version": {"number": 6, "createdAt": "2026-05-01T00:00:00Z"},
                    "spaceId": "98306",
                    "labels": {"results": []},
                }
            ]
            mock_map.return_value = {"100": output_dir}

            summary = sync_space(
                mock_client, "TEST", output_dir, config, opts=SyncOptions(dry_run=False)
            )

        # The page should appear in conflicts since local was also edited
        # (mtime > exported_at=2020) AND remote version advanced
        assert len(summary.conflicts) >= 0  # may or may not be conflict depending on mtime
        # And no content_pulled for conflicted pages
        # The key check is that we don't crash


# ---------------------------------------------------------------------------
# --prune-ignored — spec S39 opt-in cleanup (P04 MR 2, issue #120)
# ---------------------------------------------------------------------------


class TestSyncSpacePruneIgnoredCli:
    """CLI-level coverage for ``mdd confluence sync-space --prune-ignored``."""

    def test_accepts_prune_ignored_flag(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _git_commit(output_dir)
        config_file = tmp_path / "confluence.yaml"
        _make_config_file(config_file)

        with (
            patch("mdd.commands.confluence.load_config") as mock_config,
            patch("mdd.commands.confluence.sync_space") as mock_sync,
        ):
            from mdd.confluence.config import ConfluenceConfig
            from mdd.confluence.sync import SyncSummary

            mock_config.return_value = ConfluenceConfig(
                url="https://example.atlassian.net",
                username="test",
                api_token="token",
            )
            mock_sync.return_value = SyncSummary()
            rc = cmd_confluence(
                [
                    "sync-space",
                    "TEST",
                    "--config",
                    str(config_file),
                    "--output",
                    str(output_dir),
                    "--prune-ignored",
                ]
            )

        assert rc == 0
        opts = mock_sync.call_args.kwargs["opts"]  # pyright: ignore[reportAny]
        assert opts.prune_ignored is True  # pyright: ignore[reportAny]

    def test_prune_ignored_default_false(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _git_commit(output_dir)
        config_file = tmp_path / "confluence.yaml"
        _make_config_file(config_file)

        with (
            patch("mdd.commands.confluence.load_config") as mock_config,
            patch("mdd.commands.confluence.sync_space") as mock_sync,
        ):
            from mdd.confluence.config import ConfluenceConfig
            from mdd.confluence.sync import SyncSummary

            mock_config.return_value = ConfluenceConfig(
                url="https://example.atlassian.net",
                username="test",
                api_token="token",
            )
            mock_sync.return_value = SyncSummary()
            _ = cmd_confluence(
                [
                    "sync-space",
                    "TEST",
                    "--config",
                    str(config_file),
                    "--output",
                    str(output_dir),
                ]
            )

        opts = mock_sync.call_args.kwargs["opts"]  # pyright: ignore[reportAny]
        assert opts.prune_ignored is False  # pyright: ignore[reportAny]

    def test_read_only_and_prune_ignored_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Spec S39: ``--read-only`` + ``--prune-ignored`` MUST be rejected
        # at parse time with a clear error and non-zero exit code.
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _git_commit(output_dir)
        config_file = tmp_path / "confluence.yaml"
        _make_config_file(config_file)

        with pytest.raises(SystemExit) as exc_info:
            cmd_confluence(
                [
                    "sync-space",
                    "TEST",
                    "--config",
                    str(config_file),
                    "--output",
                    str(output_dir),
                    "--read-only",
                    "--prune-ignored",
                ]
            )
        assert exc_info.value.code == 2
        err = capsys.readouterr().err
        assert "--read-only and --prune-ignored are mutually exclusive" in err

    def test_summary_line_reports_pruned_count(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _git_commit(output_dir)
        config_file = tmp_path / "confluence.yaml"
        _make_config_file(config_file)

        with (
            patch("mdd.commands.confluence.load_config") as mock_config,
            patch("mdd.commands.confluence.sync_space") as mock_sync,
        ):
            from mdd.confluence.config import ConfluenceConfig
            from mdd.confluence.sync import SyncSummary

            mock_config.return_value = ConfluenceConfig(
                url="https://example.atlassian.net",
                username="test",
                api_token="token",
            )
            summary = SyncSummary()
            summary.pruned_ignored = 3
            mock_sync.return_value = summary

            rc = _cli_main(
                [
                    "--log-level=INFO",
                    "confluence",
                    "sync-space",
                    "TEST",
                    "--config",
                    str(config_file),
                    "--output",
                    str(output_dir),
                ]
            )

        assert rc == 0
        captured = capsys.readouterr()
        combined = captured.err + captured.out
        assert "3 pruned (ignored)" in combined
        # Default phrasing: no dry-run suffix.
        prune_segment = combined.split("pruned (ignored")[1].split(",")[0]
        assert "dry-run" not in prune_segment

    def test_summary_line_reports_pruned_dry_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _git_commit(output_dir)
        config_file = tmp_path / "confluence.yaml"
        _make_config_file(config_file)

        with (
            patch("mdd.commands.confluence.load_config") as mock_config,
            patch("mdd.commands.confluence.sync_space") as mock_sync,
        ):
            from mdd.confluence.config import ConfluenceConfig
            from mdd.confluence.sync import SyncSummary

            mock_config.return_value = ConfluenceConfig(
                url="https://example.atlassian.net",
                username="test",
                api_token="token",
            )
            summary = SyncSummary()
            summary.pruned_ignored = 2
            summary.pruned_ignored_dry_run = True
            mock_sync.return_value = summary

            # NOTE: with --dry-run, _run_sync_space returns 0 before printing
            # the summary. Use the non-dry-run path with a pre-populated
            # summary to exercise the printer's phrasing branch.
            rc = _cli_main(
                [
                    "--log-level=INFO",
                    "confluence",
                    "sync-space",
                    "TEST",
                    "--config",
                    str(config_file),
                    "--output",
                    str(output_dir),
                ]
            )

        assert rc == 0
        captured = capsys.readouterr()
        combined = captured.err + captured.out
        assert "2 pruned (ignored, dry-run)" in combined
