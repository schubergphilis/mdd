"""Tests for mdd.sharepoint.sync — bidirectional sync orchestrator (spec S18)."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mdd.sharepoint.sync import (
    SyncError,
    _check_dirty,  # pyright: ignore[reportPrivateUsage]
    _walk_for_pairs,  # pyright: ignore[reportPrivateUsage]
    _walk_real_files,  # pyright: ignore[reportPrivateUsage]
    _WalkStats,  # pyright: ignore[reportPrivateUsage]
    derive_site_name,
    sync_folder,
)
from mdd.utils.mddignore import MddIgnore
from tests.mirror_stub import stub_backend

# ---------------------------------------------------------------------------
# derive_site_name
# ---------------------------------------------------------------------------


class TestDeriveSiteName:
    def test_strips_documents_suffix(self) -> None:
        assert derive_site_name("HR - Documents") == "HR"

    def test_no_suffix_unchanged(self) -> None:
        assert derive_site_name("MySite") == "MySite"


# ---------------------------------------------------------------------------
# _walk_for_pairs
# ---------------------------------------------------------------------------


class TestWalkForPairs:
    def _split(self, tmp_path: Path) -> tuple[Path, Path]:
        src = tmp_path / "src"
        out = tmp_path / "out"
        src.mkdir()
        out.mkdir()
        return src, out

    def test_returns_docx_with_md_sibling(self, tmp_path: Path) -> None:
        src, out = self._split(tmp_path)
        docx = src / "Report.docx"
        docx.write_bytes(b"x")
        md = out / "Report.docx.md"
        md.write_text("# body", encoding="utf-8")

        pairs = _walk_for_pairs(src, out)
        assert len(pairs) == 1
        assert pairs[0][0] == docx
        assert pairs[0][1] == md

    def test_returns_docx_without_md_uses_intended_output_path(self, tmp_path: Path) -> None:
        """An office file with no .md yields the intended .md path under output_dir."""
        src, out = self._split(tmp_path)
        docx = src / "Report.docx"
        docx.write_bytes(b"x")

        pairs = _walk_for_pairs(src, out)
        assert len(pairs) == 1
        assert pairs[0][0] == docx
        assert pairs[0][1] == out / "Report.docx.md"
        assert not pairs[0][1].exists()

    def test_orphaned_md_in_output_detected(self, tmp_path: Path) -> None:
        """A .docx.md in *output_dir* with no corresponding .docx in source is md-only."""
        src, out = self._split(tmp_path)
        md = out / "Orphan.docx.md"
        md.write_text("# orphan", encoding="utf-8")

        pairs = _walk_for_pairs(src, out)
        assert len(pairs) == 1
        assert pairs[0][0] == src / "Orphan.docx"
        assert pairs[0][1] == md
        assert not pairs[0][0].exists()

    def test_orphaned_md_in_source_is_ignored(self, tmp_path: Path) -> None:
        """A .docx.md sitting *inside* the source tree is not a sync pair on its own.

        Output-tree placement is now the only way to declare an md-authoritative
        first-sync — preventing accidental re-use of stray files in OneDrive.
        """
        src, out = self._split(tmp_path)
        (src / "Stray.docx.md").write_text("# stray", encoding="utf-8")

        pairs = _walk_for_pairs(src, out)
        assert pairs == []

    def test_standalone_md_not_a_pair(self, tmp_path: Path) -> None:
        """A plain notes.md (not ending in .docx.md or .pptx.md) is not a sync pair."""
        src, out = self._split(tmp_path)
        (out / "notes.md").write_text("# notes", encoding="utf-8")

        pairs = _walk_for_pairs(src, out)
        assert len(pairs) == 0

    def test_pptx_pair(self, tmp_path: Path) -> None:
        src, out = self._split(tmp_path)
        pptx = src / "Deck.pptx"
        pptx.write_bytes(b"x")
        md = out / "Deck.pptx.md"
        md.write_text("# slides", encoding="utf-8")

        pairs = _walk_for_pairs(src, out)
        assert len(pairs) == 1
        assert pairs[0][0] == pptx

    def test_word_lock_files_excluded(self, tmp_path: Path) -> None:
        """~$Foo.docx lock files should not appear as pairs."""
        src, out = self._split(tmp_path)
        (src / "~$Foo.docx").write_bytes(b"lock")

        pairs = _walk_for_pairs(src, out)
        assert len(pairs) == 0

    def test_multiple_pairs_sorted(self, tmp_path: Path) -> None:
        src, out = self._split(tmp_path)
        (src / "Zzz.docx").write_bytes(b"z")
        (src / "Aaa.docx").write_bytes(b"a")
        (out / "Aaa.docx.md").write_text("# a", encoding="utf-8")

        pairs = _walk_for_pairs(src, out)
        assert pairs[0][0].name == "Aaa.docx"
        assert pairs[1][0].name == "Zzz.docx"

    def test_dotfiles_excluded(self, tmp_path: Path) -> None:
        src, out = self._split(tmp_path)
        (src / ".DS_Store").write_bytes(b"x")
        (src / "Real.docx").write_bytes(b"x")

        pairs = _walk_for_pairs(src, out)
        names = [p[0].name for p in pairs]
        assert ".DS_Store" not in names
        assert "Real.docx" in names

    def test_nested_subdirectory_mirrors_to_output(self, tmp_path: Path) -> None:
        """Directory structure under source is mirrored under output."""
        src, out = self._split(tmp_path)
        nested = src / "Reports" / "2026"
        nested.mkdir(parents=True)
        docx = nested / "Q1.docx"
        docx.write_bytes(b"x")

        pairs = _walk_for_pairs(src, out)
        assert pairs[0] == (docx, out / "Reports" / "2026" / "Q1.docx.md")

    def test_missing_output_dir_handled_gracefully(self, tmp_path: Path) -> None:
        """If output_dir does not exist yet, we still discover source pairs."""
        src = tmp_path / "src"
        src.mkdir()
        out = tmp_path / "out-does-not-exist"
        (src / "Report.docx").write_bytes(b"x")

        pairs = _walk_for_pairs(src, out)
        assert len(pairs) == 1
        assert pairs[0][1] == out / "Report.docx.md"


# ---------------------------------------------------------------------------
# _check_dirty
# ---------------------------------------------------------------------------


class TestCheckDirty:
    def test_clean_tree_does_not_raise(self, tmp_path: Path) -> None:
        mock_result = MagicMock()
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            _check_dirty(tmp_path)  # Should not raise

    def test_dirty_tree_raises(self, tmp_path: Path) -> None:
        mock_result = MagicMock()
        mock_result.stdout = " M modified_file.md\n"
        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(SyncError, match="uncommitted"),
        ):
            _check_dirty(tmp_path)

    def test_missing_git_does_not_raise(self, tmp_path: Path) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            _check_dirty(tmp_path)  # Should not raise


# ---------------------------------------------------------------------------
# sync_folder — basic integration (mocked converters)
# ---------------------------------------------------------------------------


class TestSyncFolderBasic:
    def _fake_convert(self, src: Path, dest: Path) -> str:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("# Converted", encoding="utf-8")
        return "docling-docx"

    def _fake_render(self, md_path: Path, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"rendered docx")

    def test_dirty_tree_raises(self, tmp_path: Path) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        output = tmp_path / "output"
        output.mkdir()

        mock_result = MagicMock()
        mock_result.stdout = " M modified.md\n"
        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(SyncError, match="uncommitted"),
        ):
            sync_folder(site, output_dir=output)

    def test_missing_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SyncError, match="does not exist"):
            sync_folder(tmp_path / "nonexistent", output_dir=tmp_path / "out")

    def test_file_path_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x")
        with pytest.raises(SyncError, match="not a directory"):
            sync_folder(f, output_dir=tmp_path / "out")

    def test_empty_folder_returns_zero_summary(self, tmp_path: Path) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        output = tmp_path / "output"
        output.mkdir()

        # Suppress dirty check and blacklist
        with (
            patch("subprocess.run", return_value=MagicMock(stdout="")),
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
        ):
            summary = sync_folder(site, output_dir=output)

        assert summary.first_sync_docx == 0
        assert summary.errors == []

    def test_dry_run_prints_plan_and_touches_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        (site / "Report.docx").write_bytes(b"docx")
        output = tmp_path / "output"
        output.mkdir()

        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
        ):
            sync_folder(site, output_dir=output, dry_run=True)

        out = capsys.readouterr().out
        assert "dry-run" in out
        assert "Report.docx" in out
        # No files written to output
        assert list(output.iterdir()) == []

    def test_word_locked_file_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        docx = site / "Report.docx"
        docx.write_bytes(b"docx")
        (site / "~$Report.docx").write_bytes(b"lock")
        output = tmp_path / "output"
        output.mkdir()
        (output / "Report.docx.md").write_text("# content", encoding="utf-8")

        with (
            caplog.at_level(logging.INFO, logger="mdd"),
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.apply.apply_first_sync_docx") as mock_conv,
        ):
            summary = sync_folder(site, output_dir=output)

        mock_conv.assert_not_called()
        assert summary.word_locked == 1
        assert "Word" in caplog.text

    def test_first_sync_docx_only(self, tmp_path: Path) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        docx = site / "Report.docx"
        docx.write_bytes(b"docx data")
        output = tmp_path / "output"
        output.mkdir()

        mock_apply = MagicMock()
        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.sync.apply_pair", mock_apply),
        ):
            sync_folder(site, output_dir=output)

        mock_apply.assert_called_once()
        call_kwargs = mock_apply.call_args.kwargs
        from mdd.sharepoint.diff import PairAction

        assert call_kwargs["action"] == PairAction.FIRST_SYNC_DOCX_AUTHORITATIVE

    def test_head_limits_pairs(self, tmp_path: Path) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        for i in range(5):
            (site / f"File{i}.docx").write_bytes(b"x")

        applied_pairs: list[object] = []

        def capture_apply(**kwargs: object) -> None:
            applied_pairs.append(kwargs)

        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.sync.apply_pair", side_effect=capture_apply),
        ):
            sync_folder(site, output_dir=tmp_path / "out", head=2)

        assert len(applied_pairs) == 2

    def test_push_calls_push_worktree(self, tmp_path: Path) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        output = tmp_path / "output"
        output.mkdir()
        # Pre-existing git repo: sync_folder skips bootstrap and goes straight
        # to commit + push. (Issue #132: ``is_git_repo`` uses
        # ``git rev-parse --is-inside-work-tree`` so we need a real init.)
        subprocess.run(["git", "init", "-b", "main"], cwd=str(output), check=True)

        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            stub_backend() as backend,
        ):
            sync_folder(site, output_dir=output, push=True)

        assert backend.pushes == [(output, None)]

    def test_diverged_both_sources_untouched(self, tmp_path: Path) -> None:
        import hashlib

        site = tmp_path / "MySite"
        site.mkdir()
        output = tmp_path / "output"
        output.mkdir()

        old_docx = b"original docx"
        old_md = "# original markdown"

        docx = site / "Report.docx"
        docx.write_bytes(old_docx)
        md = output / "Report.docx.md"

        docx_sha = hashlib.sha256(old_docx).hexdigest()
        md_sha = hashlib.sha256(old_md.encode()).hexdigest()

        md.write_text(
            f"---\nsharepoint:\n  sync:\n"
            f"    office_sha256_at_sync: {docx_sha}0WRONG\n"
            f"    md_sha256_at_sync: {md_sha}0WRONG\n"
            f"    update_office: true\n"
            f"---\n{old_md}\n",
            encoding="utf-8",
        )

        fake_candidate_data = b"candidate render"

        def fake_render(md_path: Path, dest: Path) -> None:
            dest.write_bytes(fake_candidate_data)

        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.apply.actions.do_render", side_effect=fake_render),
        ):
            summary = sync_folder(site, output_dir=output)

        # Both sources untouched
        assert docx.read_bytes() == old_docx
        # Candidate render lands next to the office file (per spec)
        assert (site / "Report.from-md.docx").read_bytes() == fake_candidate_data
        # Summary counts diverged
        assert summary.diverged == 1

    def test_md_edit_without_update_office_is_skipped(self, tmp_path: Path) -> None:
        """Regression: md edits must not render to office unless update_office is true."""
        import hashlib

        from mdd.sharepoint.diff import sha256_md_content

        site = tmp_path / "MySite"
        site.mkdir()
        output = tmp_path / "output"
        output.mkdir()

        docx_bytes = b"authoritative docx"
        docx = site / "Report.docx"
        docx.write_bytes(docx_bytes)

        md = output / "Report.docx.md"
        # Write the md with a sync block whose md hash matches the *original*
        # body; then edit the body so md_now drifts. update_office defaults to
        # False, so this should classify as SKIP_MD_UPDATE.
        body = "# original\n"
        md.write_text(
            f"---\nsharepoint:\n  sync:\n"
            f"    office_sha256_at_sync: {hashlib.sha256(docx_bytes).hexdigest()}\n"
            f"    md_sha256_at_sync: {hashlib.sha256(body.encode()).hexdigest()}\n"
            f"    update_office: false\n"
            f"---\n{body}",
            encoding="utf-8",
        )
        # Capture the canonical hash of the as-written file, then edit the body.
        original_md_canonical = sha256_md_content(md)
        md.write_text(
            md.read_text(encoding="utf-8").replace("# original", "# edited"),
            encoding="utf-8",
        )
        assert sha256_md_content(md) != original_md_canonical, "test setup broken"

        mock_render = MagicMock()
        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.apply.actions.do_render", mock_render),
        ):
            summary = sync_folder(site, output_dir=output)

        mock_render.assert_not_called()
        # docx left untouched
        assert docx.read_bytes() == docx_bytes
        assert summary.skipped_md_update == 1
        assert summary.md_to_docx == 0
        assert summary.diverged == 0

    def test_md_lands_in_output_not_source(self, tmp_path: Path) -> None:
        """Regression for issue #84: --output must receive the .md, not the source folder.

        For both FIRST_SYNC_DOCX (no md yet) and DOCX_TO_MD (md drifted) the
        markdown side must be written under output_dir.
        """
        site = tmp_path / "MySite"
        site.mkdir()
        (site / "Report.docx").write_bytes(b"docx data")
        output = tmp_path / "output"
        output.mkdir()

        def fake_convert(src: Path, dest: Path) -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("# Converted\n", encoding="utf-8")

        def convert_wrapper(s: Path, d: Path) -> str:
            fake_convert(s, d)
            return "docling-docx"

        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.apply.actions.do_convert", side_effect=convert_wrapper),
        ):
            summary = sync_folder(site, output_dir=output)

        # .md exists ONLY in output, not in the source folder.
        assert (output / "Report.docx.md").exists()
        assert not (site / "Report.docx.md").exists()
        assert summary.first_sync_docx == 1

    def test_read_only_suppresses_md_to_docx(self, tmp_path: Path) -> None:
        """``read_only=True`` must skip md→office renders even when md changed."""
        import hashlib

        from mdd.sharepoint.diff import sha256_md_content

        site = tmp_path / "MySite"
        site.mkdir()
        output = tmp_path / "output"
        output.mkdir()

        docx_bytes = b"office bytes"
        docx = site / "Report.docx"
        docx.write_bytes(docx_bytes)

        md = output / "Report.docx.md"
        body = "# original\n"
        # Stamp with the *body* hash; the canonical-form hash of the file as
        # written must equal sha256(body) because there's no other frontmatter.
        md.write_text(
            f"---\nsharepoint:\n  sync:\n"
            f"    office_sha256_at_sync: {hashlib.sha256(docx_bytes).hexdigest()}\n"
            f"    md_sha256_at_sync: {hashlib.sha256(body.encode()).hexdigest()}\n"
            f"    update_office: true\n"
            f"---\n{body}",
            encoding="utf-8",
        )
        canonical_before = sha256_md_content(md)
        md.write_text(
            md.read_text(encoding="utf-8").replace("# original", "# edited"),
            encoding="utf-8",
        )
        assert sha256_md_content(md) != canonical_before, "test setup broken"

        mock_render = MagicMock()
        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.apply.actions.do_render", mock_render),
        ):
            summary = sync_folder(site, output_dir=output, read_only=True)

        mock_render.assert_not_called()
        assert docx.read_bytes() == docx_bytes
        assert summary.md_to_docx == 0
        assert summary.skipped_read_only == 1
        assert summary.skipped_read_only_paths == ["Report.docx"]

    def test_read_only_suppresses_diverged_candidate(self, tmp_path: Path) -> None:
        """``read_only=True`` must skip the ``*.from-md.docx`` render on DIVERGED."""
        import hashlib

        site = tmp_path / "MySite"
        site.mkdir()
        output = tmp_path / "output"
        output.mkdir()

        old_docx = b"original docx"
        old_md = "# original markdown"

        docx = site / "Report.docx"
        docx.write_bytes(old_docx)
        md = output / "Report.docx.md"

        docx_sha = hashlib.sha256(old_docx).hexdigest()
        md_sha = hashlib.sha256(old_md.encode()).hexdigest()

        md.write_text(
            f"---\nsharepoint:\n  sync:\n"
            f"    office_sha256_at_sync: {docx_sha}0WRONG\n"
            f"    md_sha256_at_sync: {md_sha}0WRONG\n"
            f"    update_office: true\n"
            f"---\n{old_md}\n",
            encoding="utf-8",
        )

        mock_render = MagicMock()
        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.apply.actions.do_render", mock_render),
        ):
            summary = sync_folder(site, output_dir=output, read_only=True)

        mock_render.assert_not_called()
        assert docx.read_bytes() == old_docx
        assert not (site / "Report.from-md.docx").exists()
        assert summary.diverged == 0
        assert summary.skipped_read_only == 1

    def test_read_only_allows_docx_to_md(self, tmp_path: Path) -> None:
        """``read_only=True`` must still pull office → markdown changes."""
        site = tmp_path / "MySite"
        site.mkdir()
        (site / "Report.docx").write_bytes(b"docx data")
        output = tmp_path / "output"
        output.mkdir()

        def convert_wrapper(s: Path, d: Path) -> str:
            d.parent.mkdir(parents=True, exist_ok=True)
            d.write_text("# Converted\n", encoding="utf-8")
            return "docling-docx"

        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.apply.actions.do_convert", side_effect=convert_wrapper),
        ):
            summary = sync_folder(site, output_dir=output, read_only=True)

        assert (output / "Report.docx.md").exists()
        assert summary.first_sync_docx == 1
        assert summary.skipped_read_only == 0

    def test_nested_md_mirrors_source_layout_under_output(self, tmp_path: Path) -> None:
        """Sub-directory structure is preserved under output_dir."""
        site = tmp_path / "MySite"
        nested = site / "Reports" / "2026"
        nested.mkdir(parents=True)
        (nested / "Q1.docx").write_bytes(b"docx data")
        output = tmp_path / "output"
        output.mkdir()

        def convert_wrapper(s: Path, d: Path) -> str:
            d.parent.mkdir(parents=True, exist_ok=True)
            d.write_text("# Converted\n", encoding="utf-8")
            return "docling-docx"

        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.apply.actions.do_convert", side_effect=convert_wrapper),
        ):
            sync_folder(site, output_dir=output)

        assert (output / "Reports" / "2026" / "Q1.docx.md").exists()
        assert not (nested / "Q1.docx.md").exists()


# ---------------------------------------------------------------------------
# Deprecated `export site` / `export folder` forwarders were removed in PR 7
# of the S35 argparse rollout. The flat `sync-site` / `sync-folder` forms
# are the only entry points now; see tests/commands/test_sharepoint.py for
# the full subcommand coverage.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Cold-start bootstrap — output_dir is not yet a git repo
# ---------------------------------------------------------------------------


class TestColdStartBootstrap:
    """Sync-site against a fresh, non-git output dir must not crash on commit.

    Regression for the report:
        mdd sharepoint sync-site Engineering --output Engineering --read-only
        [WARN] git commit failed: Command '['git', 'add', '-A']' returned non-zero exit status 128.

    The fix mirrors confluence sync-space: skip commit when the output dir
    isn't a git repo (no --push), and bootstrap the repo (git init + ensure
    GitLab project) when --push is set.
    """

    def _convert(self, s: Path, d: Path) -> str:
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_text("# Converted\n", encoding="utf-8")
        return "docling-docx"

    def test_read_only_into_non_git_dir_does_not_crash(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        (site / "Report.docx").write_bytes(b"docx data")
        output = tmp_path / "output"
        output.mkdir()

        with (
            caplog.at_level(logging.WARNING, logger="mdd"),
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch(
                "mdd.sharepoint.apply.actions.do_convert",
                side_effect=self._convert,
            ),
        ):
            summary = sync_folder(site, output_dir=output, read_only=True)

        # The md was still written under output_dir.
        assert (output / "Report.docx.md").exists()
        assert summary.first_sync_docx == 1
        # And no "git commit failed" / "git add -A" warning was emitted.
        assert "git commit failed" not in caplog.text
        assert "git add" not in caplog.text


# ---------------------------------------------------------------------------
# `.mddignore` source-side filtering — spec S39 walker + summary wiring
# ---------------------------------------------------------------------------


def _write_ignore(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestWalkRealFilesPrunes:
    """``_walk_real_files`` honours the S39 matcher (prune + per-file skip)."""

    def test_prunes_archive_subtree(self, tmp_path: Path) -> None:
        # Tree with an `Archive/` subdir that the matcher prunes wholesale.
        src = tmp_path / "src"
        (src / "Marketing" / "Archive").mkdir(parents=True)
        (src / "Marketing" / "Current").mkdir(parents=True)
        (src / "Marketing" / "Archive" / "old.pptx").write_bytes(b"x")
        (src / "Marketing" / "Archive" / "nested" / "deeper.pptx").parent.mkdir(parents=True)
        (src / "Marketing" / "Archive" / "nested" / "deeper.pptx").write_bytes(b"x")
        (src / "Marketing" / "Current" / "live.docx").write_bytes(b"x")

        dest = tmp_path / "dest"
        dest.mkdir()
        _write_ignore(dest / ".mddignore", "**/Archive/")
        matcher = MddIgnore.load(dest)

        stats = _WalkStats()
        files = _walk_real_files(src, matcher=matcher, stats=stats)
        names = {f.name for f in files}

        # Pruned subtree never appears.
        assert "old.pptx" not in names
        assert "deeper.pptx" not in names
        # Sibling subtree walked normally.
        assert "live.docx" in names
        # And the prune got recorded.
        assert any(p == Path("Marketing/Archive") for p in stats.pruned_dirs)

    def test_per_file_skip_when_pattern_cannot_prune(self, tmp_path: Path) -> None:
        # `*.tmp` cannot prune a directory wholesale; per-file skip applies.
        src = tmp_path / "src"
        src.mkdir()
        (src / "good.docx").write_bytes(b"x")
        (src / "scratch.tmp").write_bytes(b"x")

        dest = tmp_path / "dest"
        dest.mkdir()
        _write_ignore(dest / ".mddignore", "*.tmp")
        matcher = MddIgnore.load(dest)

        stats = _WalkStats()
        files = _walk_real_files(src, matcher=matcher, stats=stats)
        names = {f.name for f in files}
        assert "good.docx" in names
        assert "scratch.tmp" not in names
        assert any(p.name == "scratch.tmp" for p in stats.skipped_files)
        assert stats.pruned_dirs == []

    def test_no_matcher_behaves_exactly_as_before(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        (src / "Marketing" / "Archive").mkdir(parents=True)
        (src / "Marketing" / "Archive" / "old.pptx").write_bytes(b"x")
        (src / "Marketing" / "live.docx").write_bytes(b"x")

        files = _walk_real_files(src)  # no matcher
        names = {f.name for f in files}
        # Nothing is filtered when no matcher is supplied.
        assert "old.pptx" in names
        assert "live.docx" in names


class TestWalkForPairsHonoursMatcher:
    def test_pruned_dir_drops_pairs(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        out = tmp_path / "out"
        src.mkdir()
        out.mkdir()
        (src / "Archive").mkdir()
        (src / "Archive" / "old.docx").write_bytes(b"x")
        (src / "live.docx").write_bytes(b"x")

        _write_ignore(out / ".mddignore", "Archive/")
        matcher = MddIgnore.load(out)

        stats = _WalkStats()
        pairs = _walk_for_pairs(src, out, matcher=matcher, stats=stats)
        office_names = {pair[0].name for pair in pairs}
        assert "live.docx" in office_names
        assert "old.docx" not in office_names
        # Pruned directory was recorded.
        assert any(p == Path("Archive") for p in stats.pruned_dirs)

    def test_no_matcher_no_skips(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        out = tmp_path / "out"
        src.mkdir()
        out.mkdir()
        (src / "Archive").mkdir()
        (src / "Archive" / "old.docx").write_bytes(b"x")
        (src / "live.docx").write_bytes(b"x")

        pairs = _walk_for_pairs(src, out)
        office_names = {pair[0].name for pair in pairs}
        # Without a matcher, both files come through.
        assert {"old.docx", "live.docx"} <= office_names


class TestSyncFolderMatcherSummary:
    """End-to-end: ``sync_folder`` rolls the prune+skip counts into the summary."""

    def _convert(self, _src: Path, dest: Path) -> str:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("# Converted\n", encoding="utf-8")
        return "docling-docx"

    def test_summary_skipped_ignored_counts_prunes_and_files(self, tmp_path: Path) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        (site / "Archive").mkdir()
        (site / "Archive" / "old1.docx").write_bytes(b"x")
        (site / "Archive" / "old2.docx").write_bytes(b"x")
        (site / "scratch.tmp").write_bytes(b"x")
        (site / "live.docx").write_bytes(b"x")
        output = tmp_path / "output"
        output.mkdir()
        _write_ignore(output / ".mddignore", "Archive/", "*.tmp")
        matcher = MddIgnore.load(output)

        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.apply.actions.do_convert", side_effect=self._convert),
        ):
            summary = sync_folder(site, output_dir=output, matcher=matcher)

        # Live pair was processed.
        assert summary.first_sync_docx == 1
        # 1 pruned dir + 1 per-file skip → 2 ignored entries.
        assert summary.skipped_ignored == 2
        assert any(p.endswith("/") for p in summary.skipped_ignored_paths)
        assert any(p.endswith("scratch.tmp") for p in summary.skipped_ignored_paths)

    def test_summary_zero_when_no_matcher_and_no_mddignore(self, tmp_path: Path) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        (site / "live.docx").write_bytes(b"x")
        output = tmp_path / "output"
        output.mkdir()
        # No matcher passed, no .mddignore file → behaviour identical to today.
        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.apply.actions.do_convert", side_effect=self._convert),
        ):
            summary = sync_folder(site, output_dir=output)

        assert summary.skipped_ignored == 0
        assert summary.skipped_ignored_paths == []

    def test_dry_run_summary_reports_skipped_ignored(self, tmp_path: Path) -> None:
        # Regression: dry-run used to return an empty SyncRunSummary, hiding
        # the matcher's effect from the user (the very thing dry-run is for).
        site = tmp_path / "MySite"
        site.mkdir()
        (site / "Archive").mkdir()
        (site / "Archive" / "old.docx").write_bytes(b"x")
        (site / "live.docx").write_bytes(b"x")
        output = tmp_path / "output"
        output.mkdir()
        _write_ignore(output / ".mddignore", "Archive/")
        matcher = MddIgnore.load(output)

        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
        ):
            summary = sync_folder(site, output_dir=output, matcher=matcher, dry_run=True)

        assert summary.skipped_ignored == 1
        assert any(p.endswith("/") for p in summary.skipped_ignored_paths)


# ---------------------------------------------------------------------------
# sync_folder — corrupt-source soft-skip (issue #129)
# ---------------------------------------------------------------------------


class TestSyncFolderCorruptSource:
    """Issue #129: empty/corrupt office files are recorded as [SKIP] not [ERROR]."""

    def test_zero_byte_docx_soft_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        # 0-byte docx — convert_docx will raise CorruptSourceError on pre-check
        (site / "Broken.docx").write_bytes(b"")
        output = tmp_path / "output"
        output.mkdir()

        with (
            caplog.at_level(logging.INFO, logger="mdd"),
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
        ):
            summary = sync_folder(site, output_dir=output)

        # Counted as skipped_corrupt, not errors
        assert summary.skipped_corrupt == 1
        assert summary.skipped_corrupt_paths == ["Broken.docx"]
        assert summary.errors == []

        assert "[SKIP] Broken.docx: corrupt or empty source" in caplog.text
        # No ERROR-level log records emitted for the corrupt-source case.
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)

    def test_garbage_pptx_soft_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        # Non-ZIP bytes — python-pptx raises PackageNotFoundError
        (site / "Broken.pptx").write_bytes(b"not a zip file")
        output = tmp_path / "output"
        output.mkdir()

        with (
            caplog.at_level(logging.INFO, logger="mdd"),
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
        ):
            summary = sync_folder(site, output_dir=output)

        assert summary.skipped_corrupt == 1
        assert summary.skipped_corrupt_paths == ["Broken.pptx"]
        assert summary.errors == []

        assert "[SKIP] Broken.pptx: corrupt or empty source" in caplog.text
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)


# ---------------------------------------------------------------------------
# --prune-ignored — spec S39 opt-in cleanup
# ---------------------------------------------------------------------------


class TestSyncFolderPruneIgnored:
    """``--prune-ignored`` deletes already-synced files that match the matcher."""

    def _convert(self, _src: Path, dest: Path) -> str:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("# Converted\n", encoding="utf-8")
        return "docling-docx"

    def test_prune_removes_matched_files_and_logs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        (site / "live.docx").write_bytes(b"x")
        output = tmp_path / "output"
        output.mkdir()
        # Two already-synced files that newly match the matcher.
        stale_dir = output / "Archive"
        stale_dir.mkdir()
        stale_file = stale_dir / "old.docx.md"
        stale_file.write_text("# old", encoding="utf-8")
        scratch = output / "scratch.tmp"
        scratch.write_text("scratch", encoding="utf-8")
        # And one file that the matcher does NOT touch.
        keep = output / "live.docx.md"
        keep.write_text("# live", encoding="utf-8")

        _write_ignore(output / ".mddignore", "Archive/", "*.tmp")
        matcher = MddIgnore.load(output)

        with (
            caplog.at_level(logging.INFO, logger="mdd"),
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
            patch("mdd.sharepoint.apply.actions.do_convert", side_effect=self._convert),
        ):
            summary = sync_folder(site, output_dir=output, matcher=matcher, prune_ignored=True)

        # Both matched files are gone, the unmatched one is left alone.
        assert not stale_file.exists()
        assert not scratch.exists()
        assert keep.exists()
        # Summary counters reflect the prune pass.
        assert summary.pruned_ignored == 2
        assert summary.pruned_ignored_dry_run is False
        assert sorted(summary.pruned_ignored_paths) == ["Archive/old.docx.md", "scratch.tmp"]
        # One INFO line per deletion.
        assert "pruned (ignored): scratch.tmp" in caplog.text
        assert "pruned (ignored): Archive/old.docx.md" in caplog.text

    def test_prune_dry_run_does_not_delete(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        output = tmp_path / "output"
        output.mkdir()
        stale = output / "scratch.tmp"
        stale.write_text("scratch", encoding="utf-8")
        _write_ignore(output / ".mddignore", "*.tmp")
        matcher = MddIgnore.load(output)

        with (
            caplog.at_level(logging.INFO, logger="mdd"),
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
        ):
            summary = sync_folder(
                site,
                output_dir=output,
                matcher=matcher,
                prune_ignored=True,
                dry_run=True,
            )

        # File is still on disk.
        assert stale.exists()
        assert summary.pruned_ignored == 1
        assert summary.pruned_ignored_dry_run is True
        # ``would prune`` log line was emitted.
        assert "would prune (ignored, dry-run): scratch.tmp" in caplog.text

    def test_no_prune_flag_leaves_files_alone(self, tmp_path: Path) -> None:
        # Regression guard: the default-off contract — passing a matcher
        # without ``--prune-ignored`` must not delete already-synced files.
        site = tmp_path / "MySite"
        site.mkdir()
        output = tmp_path / "output"
        output.mkdir()
        stale = output / "scratch.tmp"
        stale.write_text("scratch", encoding="utf-8")
        _write_ignore(output / ".mddignore", "*.tmp")
        matcher = MddIgnore.load(output)

        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
        ):
            summary = sync_folder(site, output_dir=output, matcher=matcher)

        assert stale.exists()
        assert summary.pruned_ignored == 0

    def test_prune_without_matcher_is_noop(self, tmp_path: Path) -> None:
        site = tmp_path / "MySite"
        site.mkdir()
        output = tmp_path / "output"
        output.mkdir()
        # No matcher, no .mddignore — flag set, but nothing to prune.
        keep = output / "keep.txt"
        keep.write_text("keep", encoding="utf-8")

        with (
            patch("mdd.sharepoint.sync._check_dirty"),
            patch("mdd.utils.blacklist.check_sharepoint"),
        ):
            summary = sync_folder(site, output_dir=output, prune_ignored=True)

        assert keep.exists()
        assert summary.pruned_ignored == 0
