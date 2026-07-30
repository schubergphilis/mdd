"""Tests for mdd.commands.sharepoint (CLI dispatcher)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from mdd.cli import main as cli_main
from mdd.sharepoint.sync import SyncError, SyncRootMissing
from mdd.utils.blacklist import BlacklistError

if TYPE_CHECKING:
    from pathlib import Path


def cmd_sharepoint(args: list[str]) -> int:
    """Test helper: invoke `mdd sharepoint` via the argparse entry point."""
    return cli_main(["sharepoint", *args])


class TestDispatch:
    def test_no_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_sharepoint([])
        assert exc_info.value.code == 2

    def test_unknown_subcmd_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_sharepoint(["notacommand"])
        assert exc_info.value.code == 2

    def test_list_sites_unknown_option_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_sharepoint(["list-sites", "--badopt"])
        assert exc_info.value.code == 2

    def test_list_sites_config_missing_value_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_sharepoint(["list-sites", "--config"])
        assert exc_info.value.code == 2

    def test_sync_site_config_missing_value_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_sharepoint(["sync-site", "mysite", "--config"])
        assert exc_info.value.code == 2

    def test_sync_site_output_missing_value_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_sharepoint(["sync-site", "mysite", "--output"])
        assert exc_info.value.code == 2

    def test_sync_folder_output_missing_value_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_sharepoint(["sync-folder", "/some/path", "--output"])
        assert exc_info.value.code == 2


class TestListSites:
    def test_list_sites_dispatches(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sync_root = tmp_path / "OneDrive"
        sync_root.mkdir()
        (sync_root / "Engineering - Documents").mkdir()

        mock_resolve = MagicMock(return_value=sync_root)
        with patch("mdd.commands.sharepoint.resolve_sync_root", mock_resolve):
            result = cmd_sharepoint(["list-sites"])

        assert result == 0
        out = capsys.readouterr().out
        assert "Engineering" in out

    def test_list_sites_sync_root_missing_returns_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch(
            "mdd.commands.sharepoint.resolve_sync_root",
            side_effect=SyncRootMissing("no sync root"),
        ):
            result = cmd_sharepoint(["list-sites"])
        assert result == 1
        err = capsys.readouterr().err
        assert "ERROR" in err or "Error" in err

    def test_list_sites_shows_blacklist_status(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sync_root = tmp_path / "OneDrive"
        sync_root.mkdir()
        (sync_root / "Confidential - Documents").mkdir()

        # Which sites are blacklisted is site policy; the listing's job is to
        # surface the verdict, so the gate is stubbed rather than driven off
        # the shipped data-protection.yaml.
        mock_resolve = MagicMock(return_value=sync_root)
        with (
            patch("mdd.commands.sharepoint.resolve_sync_root", mock_resolve),
            patch(
                "mdd.utils.blacklist.check_sharepoint",
                side_effect=BlacklistError("blacklisted"),
            ),
        ):
            cmd_sharepoint(["list-sites"])

        out = capsys.readouterr().out
        assert "BLOCKED" in out

    def test_list_sites_empty_shows_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sync_root = tmp_path / "OneDrive"
        sync_root.mkdir()

        mock_resolve = MagicMock(return_value=sync_root)
        with patch("mdd.commands.sharepoint.resolve_sync_root", mock_resolve):
            result = cmd_sharepoint(["list-sites"])

        assert result == 0
        out = capsys.readouterr().out
        assert "No sites found" in out


class TestSyncSite:
    def test_sync_site_dispatches_and_succeeds(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_site", return_value=summary) as mock_sync:
            result = cmd_sharepoint(["sync-site", "Engineering", "--output", str(output_dir)])

        assert result == 0
        mock_sync.assert_called_once()

    def test_sync_site_no_name_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_sharepoint(["sync-site"])
        assert exc_info.value.code == 2

    def test_sync_site_no_output_no_remote_returns_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch(
            "mdd.sharepoint.export.default_output_for_site",
            return_value=None,
        ):
            result = cmd_sharepoint(["sync-site", "Engineering"])
        assert result == 1
        err = capsys.readouterr().err
        assert "Hint" in err or "--output" in err

    def test_sync_site_blacklist_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        with patch(
            "mdd.sharepoint.sync.sync_site",
            side_effect=BlacklistError("blocked"),
        ):
            result = cmd_sharepoint(["sync-site", "Council", "--output", str(output_dir)])

        assert result == 1
        err = capsys.readouterr().err
        assert "blacklist" in err.lower() or "blocked" in err.lower()

    def test_sync_site_sync_error_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        with patch(
            "mdd.sharepoint.sync.sync_site",
            side_effect=SyncError("not found"),
        ):
            result = cmd_sharepoint(["sync-site", "Unknown", "--output", str(output_dir)])

        assert result == 1
        err = capsys.readouterr().err
        assert "ERROR" in err or "Error" in err

    def test_sync_site_with_push_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_site", return_value=summary) as mock_sync:
            result = cmd_sharepoint(
                ["sync-site", "Engineering", "--output", str(output_dir), "--push"]
            )

        assert result == 0
        mock_sync.assert_called_once()
        assert mock_sync.call_args.kwargs["push"] is True

    def test_sync_site_read_only_flag_threaded_through(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_site", return_value=summary) as mock_sync:
            result = cmd_sharepoint(
                ["sync-site", "Engineering", "--output", str(output_dir), "--read-only"]
            )

        assert result == 0
        mock_sync.assert_called_once()
        assert mock_sync.call_args.kwargs["read_only"] is True

    def test_sync_site_read_only_defaults_to_false(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_site", return_value=summary) as mock_sync:
            _ = cmd_sharepoint(["sync-site", "Engineering", "--output", str(output_dir)])

        assert mock_sync.call_args.kwargs["read_only"] is False

    def test_sync_site_errors_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = SyncRunSummary(errors=["boom"])
        with patch("mdd.sharepoint.sync.sync_site", return_value=summary):
            result = cmd_sharepoint(["sync-site", "Engineering", "--output", str(output_dir)])

        assert result == 1


class TestSyncFolder:
    def test_sync_folder_dispatches(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        folder = tmp_path / "MyFolder"
        folder.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_folder", return_value=summary) as mock_sync:
            result = cmd_sharepoint(["sync-folder", str(folder), "--output", str(output_dir)])

        assert result == 0
        mock_sync.assert_called_once()

    def test_sync_folder_no_path_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_sharepoint(["sync-folder"])
        assert exc_info.value.code == 2

    def test_sync_folder_no_output_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        folder = tmp_path / "MyFolder"
        folder.mkdir()
        result = cmd_sharepoint(["sync-folder", str(folder)])
        assert result == 1
        err = capsys.readouterr().err
        assert "--output" in err or "Hint" in err

    def test_sync_folder_sync_error_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        folder = tmp_path / "MyFolder"
        folder.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        with patch(
            "mdd.sharepoint.sync.sync_folder",
            side_effect=SyncError("no dir"),
        ):
            result = cmd_sharepoint(["sync-folder", str(folder), "--output", str(output_dir)])

        assert result == 1

    def test_sync_folder_with_push_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        folder = tmp_path / "MyFolder"
        folder.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_folder", return_value=summary) as mock_sync:
            result = cmd_sharepoint(
                ["sync-folder", str(folder), "--output", str(output_dir), "--push"]
            )

        assert result == 0
        mock_sync.assert_called_once()
        assert mock_sync.call_args.kwargs["push"] is True


class TestConfigLoading:
    def test_invalid_yaml_config_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad_config = tmp_path / "config.yaml"
        bad_config.write_text("{ invalid yaml: [")
        result = cmd_sharepoint(["list-sites", "--config", str(bad_config)])
        assert result == 1
        err = capsys.readouterr().err
        assert "ERROR" in err or "Error" in err

    def test_missing_config_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_sharepoint(["list-sites", "--config", str(tmp_path / "missing.yaml")])
        assert result == 1
        err = capsys.readouterr().err
        assert "ERROR" in err or "Error" in err

    def test_sync_site_invalid_config_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad_config = tmp_path / "config.yaml"
        bad_config.write_text("{ invalid yaml: [")
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        result = cmd_sharepoint(
            [
                "sync-site",
                "Engineering",
                "--config",
                str(bad_config),
                "--output",
                str(output_dir),
            ]
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "ERROR" in err or "Error" in err


class TestMappingFlag:
    def test_sync_site_accepts_mapping_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        mapping_file = tmp_path / "mapping.yaml"
        mapping_file.write_text("sites:\n  Engineering:\n    repo: eng\n")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_site", return_value=summary) as mock_sync:
            result = cmd_sharepoint(
                [
                    "sync-site",
                    "Engineering",
                    "--output",
                    str(output_dir),
                    "--mapping",
                    str(mapping_file),
                ]
            )

        assert result == 0
        mock_sync.assert_called_once()

    def test_list_sites_accepts_mapping_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sync_root = tmp_path / "OneDrive"
        sync_root.mkdir()
        (sync_root / "Engineering - Documents").mkdir()

        mapping_file = tmp_path / "mapping.yaml"
        mapping_file.write_text("sites:\n  Engineering:\n    repo: eng-custom\n")

        mock_resolve = MagicMock(return_value=sync_root)
        with patch("mdd.commands.sharepoint.resolve_sync_root", mock_resolve):
            result = cmd_sharepoint(["list-sites", "--mapping", str(mapping_file)])

        assert result == 0
        out = capsys.readouterr().out
        assert "eng-custom" in out


# ---------------------------------------------------------------------------
# `.mddignore` CLI wiring
# ---------------------------------------------------------------------------


class TestIgnoreFlag:
    """``--ignore=<path>`` accepted by both sync-folder and sync-site,
    matcher loaded with the supplied paths, summary line reports skip count."""

    def test_sync_folder_accepts_ignore_flag(self, tmp_path: Path) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        folder = tmp_path / "MyFolder"
        folder.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        ignore_file = tmp_path / "extra.ignore"
        ignore_file.write_text("**/Archive/*\n", encoding="utf-8")

        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_folder", return_value=summary) as mock_sync:
            result = cmd_sharepoint(
                [
                    "sync-folder",
                    str(folder),
                    "--output",
                    str(output_dir),
                    "--ignore",
                    str(ignore_file),
                ]
            )

        assert result == 0
        mock_sync.assert_called_once()
        matcher = mock_sync.call_args.kwargs["matcher"]
        assert ignore_file in matcher.sources

    def test_sync_site_accepts_ignore_flag(self, tmp_path: Path) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        output_dir = tmp_path / "out"
        output_dir.mkdir()
        ignore_file = tmp_path / "extra.ignore"
        ignore_file.write_text("**/Archive/*\n", encoding="utf-8")

        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_site", return_value=summary) as mock_sync:
            result = cmd_sharepoint(
                [
                    "sync-site",
                    "Engineering",
                    "--output",
                    str(output_dir),
                    "--ignore",
                    str(ignore_file),
                ]
            )

        assert result == 0
        matcher = mock_sync.call_args.kwargs["matcher"]
        assert ignore_file in matcher.sources

    def test_multiple_ignore_flags_union(self, tmp_path: Path) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        folder = tmp_path / "MyFolder"
        folder.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        ignore_a = tmp_path / "a.ignore"
        ignore_a.write_text("Archive/\n", encoding="utf-8")
        ignore_b = tmp_path / "b.ignore"
        ignore_b.write_text("*.tmp\n", encoding="utf-8")

        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_folder", return_value=summary) as mock_sync:
            result = cmd_sharepoint(
                [
                    "sync-folder",
                    str(folder),
                    "--output",
                    str(output_dir),
                    "--ignore",
                    str(ignore_a),
                    "--ignore",
                    str(ignore_b),
                ]
            )

        assert result == 0
        matcher = mock_sync.call_args.kwargs["matcher"]
        # Union: both CLI files appear in the matcher sources.
        assert ignore_a in matcher.sources
        assert ignore_b in matcher.sources

    def test_no_ignore_flag_or_file_means_empty_matcher(self, tmp_path: Path) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        folder = tmp_path / "MyFolder"
        folder.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_folder", return_value=summary) as mock_sync:
            result = cmd_sharepoint(["sync-folder", str(folder), "--output", str(output_dir)])

        assert result == 0
        matcher = mock_sync.call_args.kwargs["matcher"]
        # No dest-root file, no CLI flag → empty source list.
        assert matcher.sources == ()

    def test_dest_mddignore_loaded_without_flag(self, tmp_path: Path) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        folder = tmp_path / "MyFolder"
        folder.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        (output_dir / ".mddignore").write_text("Archive/\n", encoding="utf-8")

        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_folder", return_value=summary) as mock_sync:
            result = cmd_sharepoint(["sync-folder", str(folder), "--output", str(output_dir)])

        assert result == 0
        matcher = mock_sync.call_args.kwargs["matcher"]
        assert (output_dir / ".mddignore") in matcher.sources

    def test_sync_site_accepts_prune_ignored_flag(self, tmp_path: Path) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        output_dir = tmp_path / "out"
        output_dir.mkdir()
        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_site", return_value=summary) as mock_sync:
            result = cmd_sharepoint(
                [
                    "sync-site",
                    "Engineering",
                    "--output",
                    str(output_dir),
                    "--prune-ignored",
                ]
            )

        assert result == 0
        assert mock_sync.call_args.kwargs["prune_ignored"] is True

    def test_sync_site_prune_ignored_default_false(self, tmp_path: Path) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        output_dir = tmp_path / "out"
        output_dir.mkdir()
        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_site", return_value=summary) as mock_sync:
            _ = cmd_sharepoint(["sync-site", "Engineering", "--output", str(output_dir)])
        assert mock_sync.call_args.kwargs["prune_ignored"] is False

    def test_sync_folder_accepts_prune_ignored_flag(self, tmp_path: Path) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        folder = tmp_path / "MyFolder"
        folder.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        summary = SyncRunSummary()
        with patch("mdd.sharepoint.sync.sync_folder", return_value=summary) as mock_sync:
            result = cmd_sharepoint(
                [
                    "sync-folder",
                    str(folder),
                    "--output",
                    str(output_dir),
                    "--prune-ignored",
                ]
            )

        assert result == 0
        assert mock_sync.call_args.kwargs["prune_ignored"] is True

    def test_sync_site_read_only_and_prune_ignored_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # ``--read-only`` + ``--prune-ignored`` MUST be rejected
        # at parse time with a clear error and non-zero exit code.
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        with pytest.raises(SystemExit) as exc_info:
            cmd_sharepoint(
                [
                    "sync-site",
                    "Engineering",
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
        from mdd.sharepoint.apply import SyncRunSummary

        folder = tmp_path / "MyFolder"
        folder.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        summary = SyncRunSummary()
        summary.pruned_ignored = 3
        with patch("mdd.sharepoint.sync.sync_folder", return_value=summary):
            result = cli_main(
                [
                    "--log-level=INFO",
                    "sharepoint",
                    "sync-folder",
                    str(folder),
                    "--output",
                    str(output_dir),
                ]
            )
        assert result == 0
        out = capsys.readouterr()
        assert "3 pruned (ignored)" in out.err or "3 pruned (ignored)" in out.out
        # Default phrasing (no dry-run).
        assert "dry-run" not in (out.err + out.out).split("pruned (ignored")[1].split(",")[0]

    def test_summary_line_reports_pruned_dry_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        folder = tmp_path / "MyFolder"
        folder.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        summary = SyncRunSummary()
        summary.pruned_ignored = 2
        summary.pruned_ignored_dry_run = True
        with patch("mdd.sharepoint.sync.sync_folder", return_value=summary):
            result = cli_main(
                [
                    "--log-level=INFO",
                    "sharepoint",
                    "sync-folder",
                    str(folder),
                    "--output",
                    str(output_dir),
                ]
            )
        assert result == 0
        out = capsys.readouterr()
        assert "2 pruned (ignored, dry-run)" in out.err or "2 pruned (ignored, dry-run)" in out.out

    def test_summary_line_reports_skip_count(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mdd.sharepoint.apply import SyncRunSummary

        folder = tmp_path / "MyFolder"
        folder.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = SyncRunSummary()
        summary.skipped_ignored = 7
        with patch("mdd.sharepoint.sync.sync_folder", return_value=summary):
            # Sync summary now goes through log.info; raise the level to capture it.
            result = cli_main(
                [
                    "--log-level=INFO",
                    "sharepoint",
                    "sync-folder",
                    str(folder),
                    "--output",
                    str(output_dir),
                ]
            )

        assert result == 0
        captured = capsys.readouterr()
        assert "7 skipped (ignored)" in captured.err or "7 skipped (ignored)" in captured.out
