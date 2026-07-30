"""Tests for ``mdd.utils.mddignore``."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdd.utils.mddignore import MddIgnore


def _write_ignore(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestLoadAndIsIgnored:
    def test_loads_dest_root_mddignore(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "*/Archive/*")
        m = MddIgnore.load(tmp_path)
        assert m.is_ignored(Path("Marketing/Archive/foo.pptx"), is_dir=False)
        assert not m.is_ignored(Path("Marketing/Current/foo.pptx"), is_dir=False)
        assert (tmp_path / ".mddignore") in m.sources

    def test_loads_from_cli_ignore_path(self, tmp_path: Path) -> None:
        cli_file = tmp_path / "custom.ignore"
        _write_ignore(cli_file, "*/old/*")
        m = MddIgnore.load(tmp_path, cli_file)
        assert m.is_ignored(Path("Projects/old/x.docx"), is_dir=False)
        assert cli_file in m.sources

    def test_cli_ignore_accepts_tuple_of_paths(self, tmp_path: Path) -> None:
        cli_a = tmp_path / "a.ignore"
        cli_b = tmp_path / "b.ignore"
        _write_ignore(cli_a, "*/Archive/*")
        _write_ignore(cli_b, "*/old/*")
        m = MddIgnore.load(tmp_path, (cli_a, cli_b))
        assert m.is_ignored(Path("X/Archive/y"), is_dir=False)
        assert m.is_ignored(Path("X/old/z"), is_dir=False)
        # CLI sources preserve order.
        assert m.sources == (cli_a, cli_b)

    def test_union_dest_and_cli(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "*/Archive/*")
        cli = tmp_path / "extra.ignore"
        _write_ignore(cli, "*/old/*")
        m = MddIgnore.load(tmp_path, cli)
        assert m.is_ignored(Path("Marketing/Archive/foo"), is_dir=False)
        assert m.is_ignored(Path("Projects/old/foo"), is_dir=False)
        # Dest file comes first in sources order, then CLI.
        assert m.sources == (tmp_path / ".mddignore", cli)

    def test_no_files_matches_nothing(self, tmp_path: Path) -> None:
        m = MddIgnore.load(tmp_path)
        assert not m.is_ignored(Path("foo.pptx"), is_dir=False)
        assert not m.is_ignored(Path("anything/at/all"), is_dir=False)
        assert m.sources == ()

    def test_empty_mddignore_matches_nothing(self, tmp_path: Path) -> None:
        (tmp_path / ".mddignore").write_text("", encoding="utf-8")
        m = MddIgnore.load(tmp_path)
        assert not m.is_ignored(Path("foo.pptx"), is_dir=False)

    def test_comments_and_blank_lines_ignored(self, tmp_path: Path) -> None:
        _write_ignore(
            tmp_path / ".mddignore",
            "# this is a comment",
            "",
            "*.tmp",
            "  ",
        )
        m = MddIgnore.load(tmp_path)
        assert m.is_ignored(Path("foo.tmp"), is_dir=False)

    def test_missing_cli_path_silently_empty(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.ignore"
        m = MddIgnore.load(tmp_path, missing)
        assert not m.is_ignored(Path("foo.tmp"), is_dir=False)
        # CLI path is still recorded in sources even when missing.
        assert missing in m.sources

    def test_none_cli_arg_omits_cli(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "*.bak")
        m = MddIgnore.load(tmp_path, None)
        assert m.is_ignored(Path("foo.bak"), is_dir=False)


class TestEscapeSanity:
    def test_dot_tmp_does_not_match_tmp_md(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "*.tmp")
        m = MddIgnore.load(tmp_path)
        assert m.is_ignored(Path("foo.tmp"), is_dir=False)
        assert not m.is_ignored(Path("foo.tmp.md"), is_dir=False)

    def test_dot_is_literal(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "*.tmp")
        m = MddIgnore.load(tmp_path)
        # The '.' in '*.tmp' is a literal, not a regex any-char.
        assert not m.is_ignored(Path("fooXtmp"), is_dir=False)


class TestPruneDir:
    def test_archive_pattern_prunes_archive_directory(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "*/Archive/*")
        m = MddIgnore.load(tmp_path)
        # Every file under Marketing/Archive matches, so the dir is prunable.
        assert m.is_ignored(Path("Marketing/Archive/foo.pptx"), is_dir=False)
        assert m.prune_dir(Path("Marketing/Archive"))

    def test_trailing_slash_pattern_prunes(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "*/Archive/", "Archive/", "**/old/")
        m = MddIgnore.load(tmp_path)
        assert m.prune_dir(Path("Marketing/Archive"))
        assert m.prune_dir(Path("Archive"))
        # `**/old/` should match at arbitrary depth.
        assert m.prune_dir(Path("Projects/L22/old"))

    def test_non_anchored_extension_pattern_does_not_prune(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "**/*.tmp")
        m = MddIgnore.load(tmp_path)
        # A directory may still contain non-.tmp siblings — cannot prune.
        assert not m.prune_dir(Path("Marketing"))
        assert not m.prune_dir(Path("Marketing/Archive"))

    def test_unrelated_directory_not_prunable(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "*/Archive/*")
        m = MddIgnore.load(tmp_path)
        assert not m.prune_dir(Path("Marketing/Current"))
        assert not m.prune_dir(Path("Marketing"))

    def test_no_patterns_never_prunes(self, tmp_path: Path) -> None:
        m = MddIgnore.load(tmp_path)
        assert not m.prune_dir(Path("Marketing/Archive"))
        assert not m.prune_dir(Path())


class TestUnicodePaths:
    def test_unicode_folder_name_matches(self, tmp_path: Path) -> None:
        # SharePoint commonly produces folder names with curly quotes.
        _write_ignore(tmp_path / ".mddignore", "*/Archive/*")
        m = MddIgnore.load(tmp_path)
        curly = "L19’s Stuff/Archive/deck.pptx"
        assert m.is_ignored(Path(curly), is_dir=False)

    def test_unicode_pattern_matches_unicode_path(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "Café/*")
        m = MddIgnore.load(tmp_path)
        assert m.is_ignored(Path("Café/menu.docx"), is_dir=False)
        assert not m.is_ignored(Path("Cafe/menu.docx"), is_dir=False)

    def test_unicode_dir_is_prunable(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "Café/")
        m = MddIgnore.load(tmp_path)
        assert m.prune_dir(Path("Café"))


class TestWalkPrunable:
    """The opt-in cleanup helper: enumerate ignored files under dest_root."""

    def test_basic_match_yields_ignored_files(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "*.tmp", "Archive/")
        (tmp_path / "Archive").mkdir()
        (tmp_path / "Archive" / "old.docx").write_bytes(b"x")
        (tmp_path / "scratch.tmp").write_bytes(b"x")
        (tmp_path / "keep.docx").write_bytes(b"x")
        m = MddIgnore.load(tmp_path)

        prunable = sorted(p.relative_to(tmp_path).as_posix() for p in m.walk_prunable(tmp_path))
        assert prunable == ["Archive/old.docx", "scratch.tmp"]

    def test_mddignore_self_skipped(self, tmp_path: Path) -> None:
        # The matcher source-of-truth is never a deletion target — even
        # though a pattern like ``.*`` would technically match it.
        _write_ignore(tmp_path / ".mddignore", "*")
        (tmp_path / "keep.txt").write_bytes(b"x")
        m = MddIgnore.load(tmp_path)
        prunable = [p.name for p in m.walk_prunable(tmp_path)]
        assert ".mddignore" not in prunable

    def test_root_level_dotfiles_skipped(self, tmp_path: Path) -> None:
        # ``.git/`` etc. are never owned by the matcher; they are carved
        # out explicitly.
        _write_ignore(tmp_path / ".mddignore", "*")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (tmp_path / ".gitlab-ci.yml").write_text("stages: []\n", encoding="utf-8")
        (tmp_path / "doc.txt").write_bytes(b"x")
        m = MddIgnore.load(tmp_path)
        prunable = [p.relative_to(tmp_path).as_posix() for p in m.walk_prunable(tmp_path)]
        assert ".git/HEAD" not in prunable
        assert ".gitlab-ci.yml" not in prunable
        assert "doc.txt" in prunable

    def test_empty_matcher_yields_nothing(self, tmp_path: Path) -> None:
        # No .mddignore, no --ignore → walk_prunable is a cheap no-op
        # (callers depend on this for the default-off contract).
        (tmp_path / "anything.docx").write_bytes(b"x")
        (tmp_path / "Archive").mkdir()
        (tmp_path / "Archive" / "old.docx").write_bytes(b"x")
        m = MddIgnore.load(tmp_path)
        assert list(m.walk_prunable(tmp_path)) == []

    def test_missing_dest_root_yields_nothing(self, tmp_path: Path) -> None:
        m = MddIgnore.load(tmp_path)
        assert list(m.walk_prunable(tmp_path / "does-not-exist")) == []

    def test_symlink_escape_refused(self, tmp_path: Path) -> None:
        # A symlink under dest_root whose target is OUTSIDE dest_root must
        # not be yielded — pruning would delete from another tree.
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_target = outside / "secret.tmp"
        outside_target.write_bytes(b"x")

        dest = tmp_path / "dest"
        dest.mkdir()
        _write_ignore(dest / ".mddignore", "*.tmp")
        try:
            (dest / "link.tmp").symlink_to(outside_target)
        except OSError:
            pytest.skip("symlinks not supported on this platform")

        m = MddIgnore.load(dest)
        prunable = list(m.walk_prunable(dest))
        # The symlink resolves outside dest_root and must be refused.
        assert prunable == []
        # And the actual target file is still on disk.
        assert outside_target.exists()

    def test_nested_dotfile_directory_walked_normally(self, tmp_path: Path) -> None:
        # The dotfile/.mddignore carve-out is ROOT-only; nested directories
        # like ``Marketing/.cache/`` follow normal matcher rules.
        _write_ignore(tmp_path / ".mddignore", "**/*.tmp")
        (tmp_path / "Marketing").mkdir()
        nested = tmp_path / "Marketing" / ".cache"
        nested.mkdir()
        (nested / "x.tmp").write_bytes(b"x")
        m = MddIgnore.load(tmp_path)
        prunable = [p.relative_to(tmp_path).as_posix() for p in m.walk_prunable(tmp_path)]
        assert "Marketing/.cache/x.tmp" in prunable


class TestIsIgnoredDirSemantics:
    def test_directory_only_pattern_requires_is_dir(self, tmp_path: Path) -> None:
        _write_ignore(tmp_path / ".mddignore", "Archive/")
        m = MddIgnore.load(tmp_path)
        # Trailing-slash pattern matches when treated as directory.
        assert m.is_ignored(Path("Archive"), is_dir=True)
        # A file literally named "Archive" should not match a dir-only pattern.
        assert not m.is_ignored(Path("Archive"), is_dir=False)
