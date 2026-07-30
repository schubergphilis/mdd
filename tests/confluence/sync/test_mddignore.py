"""Tests for the ``.mddignore`` wiring in ``mdd confluence sync-space``."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from mdd.confluence.config import ConfluenceConfig
from mdd.confluence.sync import SyncOptions, sync_space
from mdd.confluence.sync.mddignore import build_page_rel_paths, filter_desired
from mdd.confluence.sync_diff import DesiredPage
from mdd.utils.mddignore import MddIgnore

# ---------------------------------------------------------------------------
# helpers
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


def _write_ignore(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _dp(page_id: str, title: str, parent_id: str | None = None) -> DesiredPage:
    return DesiredPage(
        page_id=page_id,
        title=title,
        parent_id=parent_id,
        status="CURRENT",
        version_number=1,
        version_created_at="2026-01-01T00:00:00Z",
        space_id="98306",
    )


# ---------------------------------------------------------------------------
# build_page_rel_paths — rel-path comes from the title chain
# ---------------------------------------------------------------------------


class TestBuildPageRelPaths:
    def test_root_page_rel_path_is_title_md(self) -> None:
        desired = {"100": _dp("100", "Root Page")}
        client = MagicMock()
        client.get_folder.side_effect = Exception("no folders")

        rels = build_page_rel_paths(desired, client)
        assert "100" in rels
        assert str(rels["100"].md_rel) == "Root Page.md"
        assert str(rels["100"].child_rel) == "Root Page"

    def test_child_page_inherits_title_chain(self) -> None:
        desired = {
            "100": _dp("100", "Archive"),
            "200": _dp("200", "Old Doc", parent_id="100"),
        }
        client = MagicMock()
        client.get_folder.side_effect = Exception("no folders")

        rels = build_page_rel_paths(desired, client)
        # Child page lives under the parent's title-named directory.
        assert str(rels["200"].md_rel) == "Archive/Old Doc.md"
        assert str(rels["200"].child_rel) == "Archive/Old Doc"

    def test_nbsp_title_rel_path_uses_ascii_space(self) -> None:
        # A title with U+00A0 NO-BREAK SPACE between words must
        # produce the same rel-path as the plain-ASCII-space equivalent, so
        # the synthetic path agrees with both the real export path
        # (export.build_path_map, which also calls `sanitize`) and a
        # `.mddignore` pattern typed with ordinary spaces.
        title = "Malicious\xa0litellm\xa0Supply\xa0Chain\xa0Attack"
        desired = {"100": _dp("100", title)}
        client = MagicMock()
        client.get_folder.side_effect = Exception("no folders")

        rels = build_page_rel_paths(desired, client)
        assert str(rels["100"].md_rel) == "Malicious litellm Supply Chain Attack.md"


# ---------------------------------------------------------------------------
# filter_desired — pattern match, prune subtree, preserve tracked
# ---------------------------------------------------------------------------


class TestFilterDesired:
    def test_pattern_drops_matching_root_page(self, tmp_path: Path) -> None:
        desired = {
            "100": _dp("100", "Archive"),
            "200": _dp("200", "Current"),
        }
        client = MagicMock()
        client.get_folder.side_effect = Exception("no folders")

        _write_ignore(tmp_path / ".mddignore", "Archive/")
        matcher = MddIgnore.load(tmp_path)

        filtered, skipped = filter_desired(desired, set(), matcher, client)
        assert "100" not in filtered
        assert "200" in filtered
        # Archive/ is prunable → records the subtree, not the .md.
        assert any(p == "Archive/" for p in skipped)

    def test_prune_dir_drops_entire_subtree(self, tmp_path: Path) -> None:
        desired = {
            "100": _dp("100", "Archive"),
            "200": _dp("200", "Old Doc", parent_id="100"),
            "300": _dp("300", "Deeper", parent_id="200"),
            "999": _dp("999", "Live"),
        }
        client = MagicMock()
        client.get_folder.side_effect = Exception("no folders")

        _write_ignore(tmp_path / ".mddignore", "Archive/")
        matcher = MddIgnore.load(tmp_path)

        filtered, skipped = filter_desired(desired, set(), matcher, client)
        # Entire subtree dropped in one shot.
        assert set(filtered.keys()) == {"999"}
        # The pruned directory appears once with a trailing slash; descendants
        # do NOT contribute extra entries (one prune = one skip line).
        prune_entries = [p for p in skipped if p.endswith("/")]
        assert any(p == "Archive/" for p in prune_entries)

    def test_already_tracked_pages_are_preserved(self, tmp_path: Path) -> None:
        # Page "100" matches the pattern but is already in mirror.tracked —
        # MUST NOT be dropped: ignore only blocks new pulls.
        desired = {"100": _dp("100", "Archive")}
        client = MagicMock()
        client.get_folder.side_effect = Exception("no folders")

        _write_ignore(tmp_path / ".mddignore", "Archive/")
        matcher = MddIgnore.load(tmp_path)

        filtered, skipped = filter_desired(desired, {"100"}, matcher, client)
        assert "100" in filtered
        assert skipped == []

    def test_nbsp_title_matches_ascii_space_pattern(self, tmp_path: Path) -> None:
        # A page titled with U+00A0 between words must be
        # filtered by a `.mddignore` pattern typed with plain ASCII spaces.
        title = "Malicious\xa0litellm\xa0Supply\xa0Chain\xa0Attack"
        desired = {
            "100": _dp("100", title),
            "200": _dp("200", "Current"),
        }
        client = MagicMock()
        client.get_folder.side_effect = Exception("no folders")

        _write_ignore(tmp_path / ".mddignore", "Malicious litellm Supply Chain Attack.md")
        matcher = MddIgnore.load(tmp_path)

        filtered, skipped = filter_desired(desired, set(), matcher, client)
        assert "100" not in filtered
        assert "200" in filtered
        assert any(p == "Malicious litellm Supply Chain Attack.md" for p in skipped)

    def test_no_patterns_no_filtering(self, tmp_path: Path) -> None:
        desired = {"100": _dp("100", "Archive"), "200": _dp("200", "Live")}
        client = MagicMock()
        client.get_folder.side_effect = Exception("no folders")

        # Empty matcher (no on-disk file, no CLI paths).
        matcher = MddIgnore.load(tmp_path)
        filtered, skipped = filter_desired(desired, set(), matcher, client)
        assert filtered == desired
        assert skipped == []


# ---------------------------------------------------------------------------
# sync_space end-to-end: matcher rolls into SyncSummary
# ---------------------------------------------------------------------------


def _make_get_side_effect(data: dict[str, Any]) -> Any:  # pyright: ignore[reportAny]
    def _get(path: str, **kwargs: Any) -> dict[str, Any]:  # pyright: ignore[reportAny]
        if "spaces" in path:
            return {"results": [{"id": data["space_id"], "key": "TEST"}], "_links": {}}
        if "pages" in path:
            return {"results": data["pages"], "_links": {}}
        return {"results": [], "_links": {}}

    return _get


class TestSyncSpaceMatcherSummary:
    """End-to-end: ``sync_space`` rolls the matcher's skips into the summary."""

    def test_archive_pages_skipped_and_counted(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _write_ignore(output_dir / ".mddignore", "Archive/")
        _git_commit(output_dir, "add ignore")
        matcher = MddIgnore.load(output_dir)

        config = ConfluenceConfig(
            url="https://example.atlassian.net",
            username="test",
            api_token="token",
        )

        mock_client = MagicMock()
        mock_client.get.side_effect = _make_get_side_effect({"space_id": "98306", "pages": []})
        mock_client.get_folder.side_effect = Exception("no folders")

        pages_payload: list[dict[str, Any]] = [
            {
                "id": "100",
                "title": "Archive",
                "parentId": None,
                "status": "current",
                "version": {"number": 1, "createdAt": "2026-01-01T00:00:00Z"},
                "spaceId": "98306",
                "labels": {"results": []},
            },
            {
                "id": "200",
                "title": "Old Page",
                "parentId": "100",
                "status": "current",
                "version": {"number": 1, "createdAt": "2026-01-01T00:00:00Z"},
                "spaceId": "98306",
                "labels": {"results": []},
            },
            {
                "id": "300",
                "title": "Live Page",
                "parentId": None,
                "status": "current",
                "version": {"number": 1, "createdAt": "2026-01-01T00:00:00Z"},
                "spaceId": "98306",
                "labels": {"results": []},
            },
        ]

        with (
            patch("mdd.confluence.sync.get_space_id", return_value="98306"),
            patch("mdd.confluence.sync.state.list_pages_for_sync") as mock_list,
            # We don't want to actually export pages — just confirm the
            # matcher filtered them out before the diff classified them.
            patch("mdd.confluence.sync.pull.export_page") as mock_export,
        ):
            mock_list.return_value = pages_payload
            mock_export.return_value = output_dir / "Live Page.md"
            summary = sync_space(
                mock_client,
                "TEST",
                output_dir,
                config,
                opts=SyncOptions(dry_run=False, matcher=matcher),
            )

        # Archive/ was prunable → one entry in the skip list with trailing slash.
        # The "Old Page" descendant is rolled into that single prune entry.
        assert summary.skipped_ignored >= 1
        assert any(p.endswith("Archive/") for p in summary.skipped_ignored_paths)
        # And the Confluence-side new event only ran for the live page.
        assert mock_export.call_count == 1

    def test_no_matcher_no_skips(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _git_commit(output_dir)

        config = ConfluenceConfig(
            url="https://example.atlassian.net",
            username="test",
            api_token="token",
        )
        mock_client = MagicMock()
        mock_client.get_folder.side_effect = Exception("no folders")

        with (
            patch("mdd.confluence.sync.get_space_id", return_value="98306"),
            patch("mdd.confluence.sync.state.list_pages_for_sync") as mock_list,
            patch("mdd.confluence.sync.pull.export_page") as mock_export,
        ):
            mock_list.return_value = [
                {
                    "id": "100",
                    "title": "Live",
                    "parentId": None,
                    "status": "current",
                    "version": {"number": 1, "createdAt": "2026-01-01T00:00:00Z"},
                    "spaceId": "98306",
                    "labels": {"results": []},
                }
            ]
            mock_export.return_value = output_dir / "Live.md"
            summary = sync_space(
                mock_client,
                "TEST",
                output_dir,
                config,
                opts=SyncOptions(dry_run=False),
            )

        # Without a matcher, behaviour is byte-identical to today's.
        assert summary.skipped_ignored == 0
        assert summary.skipped_ignored_paths == []

    def test_already_synced_page_not_dropped_on_new_pattern(self, tmp_path: Path) -> None:
        """Adding a pattern must NOT delete already-synced pages."""
        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)

        # Pre-populate mirror with a page that matches the soon-to-be-added pattern.
        page_md = output_dir / "Archive.md"
        page_md.write_text(
            "---\nconfluence:\n  page_id: '100'\n  title: Archive\n  version: 1\n"
            "  status: CURRENT\n  space_key: TEST\n  space_id: '98306'\n"
            "  parent_id: null\n  exported_at: '2026-01-01T00:00:00Z'\n---\n\n# Archive\n"
        )
        _git_commit(output_dir, "pre-existing")

        _write_ignore(output_dir / ".mddignore", "Archive/")
        # Dirty tree now because .mddignore is untracked. Commit it so the
        # dirty-check passes.
        _git_commit(output_dir, "add ignore")

        matcher = MddIgnore.load(output_dir)

        config = ConfluenceConfig(
            url="https://example.atlassian.net",
            username="test",
            api_token="token",
        )
        mock_client = MagicMock()
        mock_client.get_folder.side_effect = Exception("no folders")

        with (
            patch("mdd.confluence.sync.get_space_id", return_value="98306"),
            patch("mdd.confluence.sync.state.list_pages_for_sync") as mock_list,
            patch("mdd.confluence.sync.state.build_parent_path_map") as mock_map,
        ):
            mock_list.return_value = [
                {
                    "id": "100",
                    "title": "Archive",
                    "parentId": None,
                    "status": "current",
                    "version": {"number": 1, "createdAt": "2026-01-01T00:00:00Z"},
                    "spaceId": "98306",
                    "labels": {"results": []},
                }
            ]
            mock_map.return_value = {"100": output_dir}
            summary = sync_space(
                mock_client,
                "TEST",
                output_dir,
                config,
                opts=SyncOptions(dry_run=False, matcher=matcher),
            )

        # File is still on disk — nothing got deleted.
        assert page_md.exists()
        # And the existing page wasn't counted as ignored (only new pulls are).
        assert summary.skipped_ignored == 0
        assert summary.deleted == 0


# ---------------------------------------------------------------------------
# CLI flag wiring
# ---------------------------------------------------------------------------


class TestSyncSpaceIgnoreFlag:
    def test_ignore_flag_loads_matcher_with_cli_path(self, tmp_path: Path) -> None:
        from mdd.cli import main as _cli_main

        output_dir = tmp_path / "mirror"
        _init_git_repo(output_dir)
        _git_commit(output_dir)
        config_file = tmp_path / "confluence.yaml"
        config_file.write_text(
            "confluence:\n  url: https://example.atlassian.net\n"
            "  username: test\n  api_token: dummy-token\n"
        )

        ignore_file = tmp_path / "extra-ignore"
        _write_ignore(ignore_file, "Templates/")

        with (
            patch("mdd.commands.confluence.load_config") as mock_config,
            patch("mdd.commands.confluence.sync_space") as mock_sync,
        ):
            from mdd.confluence.sync import SyncSummary

            mock_config.return_value = ConfluenceConfig(
                url="https://example.atlassian.net", username="test", api_token="t"
            )
            mock_sync.return_value = SyncSummary()
            _cli_main(
                [
                    "confluence",
                    "sync-space",
                    "TEST",
                    "--config",
                    str(config_file),
                    "--output",
                    str(output_dir),
                    "--ignore",
                    str(ignore_file),
                ]
            )

        call_kwargs = mock_sync.call_args
        assert call_kwargs is not None
        opts = call_kwargs.kwargs["opts"]  # pyright: ignore[reportAny]
        assert opts.matcher is not None  # pyright: ignore[reportAny]
        # The CLI-supplied ignore file made it into the matcher's sources.
        assert any(  # pyright: ignore[reportAny]
            Path(s) == ignore_file
            for s in opts.matcher.sources  # pyright: ignore[reportAny]
        )
