"""Tests for mdd.search.filters — blacklist gating and frontmatter detection."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from mdd.search.filters import filter_blacklisted, frontmatter_line_range, is_frontmatter_line
from mdd.search.roots import MirrorRoot

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_root(
    path: Path,
    source_type: str = "confluence",
    identifier: str = "ENGINEERING",
) -> MirrorRoot:
    return MirrorRoot(
        path=path,
        mirror_name=f"{source_type}/{identifier}",
        source_type=source_type,
        identifier=identifier,
    )


# ---------------------------------------------------------------------------
# filter_blacklisted
# ---------------------------------------------------------------------------


class TestFilterBlacklisted:
    def _blacklist_file(self, tmp_path: Path) -> Path:
        f = tmp_path / "bl.yaml"
        f.write_text(
            textwrap.dedent(
                """\
                confluence:
                  blacklisted_spaces:
                    - HRPRIV
                sharepoint:
                  blacklisted_sites:
                    - Council
                """
            )
        )
        return f

    def test_removes_blacklisted_confluence_space(self, tmp_path: Path) -> None:
        d = tmp_path / "d"
        d.mkdir()
        root = _make_root(d, source_type="confluence", identifier="HRPRIV")
        bl = self._blacklist_file(tmp_path)
        result = filter_blacklisted([root], blacklist_file=bl)
        assert result == []

    def test_keeps_safe_confluence_space(self, tmp_path: Path) -> None:
        d = tmp_path / "d"
        d.mkdir()
        root = _make_root(d, source_type="confluence", identifier="ENGINEERING")
        bl = self._blacklist_file(tmp_path)
        result = filter_blacklisted([root], blacklist_file=bl)
        assert result == [root]

    def test_removes_blacklisted_sharepoint_site(self, tmp_path: Path) -> None:
        d = tmp_path / "d"
        d.mkdir()
        root = _make_root(d, source_type="sharepoint", identifier="Council")
        bl = self._blacklist_file(tmp_path)
        result = filter_blacklisted([root], blacklist_file=bl)
        assert result == []

    def test_keeps_safe_sharepoint_site(self, tmp_path: Path) -> None:
        d = tmp_path / "d"
        d.mkdir()
        root = _make_root(d, source_type="sharepoint", identifier="Engineering")
        bl = self._blacklist_file(tmp_path)
        result = filter_blacklisted([root], blacklist_file=bl)
        assert result == [root]

    def test_keeps_lucid_root_regardless(self, tmp_path: Path) -> None:
        d = tmp_path / "d"
        d.mkdir()
        root = _make_root(d, source_type="lucid", identifier="Council")
        bl = self._blacklist_file(tmp_path)
        result = filter_blacklisted([root], blacklist_file=bl)
        assert result == [root]

    def test_keeps_docs_root_regardless(self, tmp_path: Path) -> None:
        d = tmp_path / "d"
        d.mkdir()
        root = _make_root(d, source_type="docs", identifier="my-repo")
        bl = self._blacklist_file(tmp_path)
        result = filter_blacklisted([root], blacklist_file=bl)
        assert result == [root]

    def test_fail_open_on_missing_blacklist_config(self, tmp_path: Path) -> None:
        """When blacklist config is missing, root is kept (fail-open per spec S07 §6)."""
        d = tmp_path / "d"
        d.mkdir()
        root = _make_root(d, source_type="confluence", identifier="SECRET")
        # Use a non-existent blacklist file
        missing_bl = tmp_path / "no-such-file.yaml"
        import sys
        from io import StringIO

        old_stderr = sys.stderr
        sys.stderr = StringIO()
        try:
            result = filter_blacklisted([root], blacklist_file=missing_bl)
        finally:
            sys.stderr = old_stderr
        assert result == [root]

    def test_filters_multiple_mixed(self, tmp_path: Path) -> None:
        """Mixed list: only blacklisted ones removed."""
        d1 = tmp_path / "d1"
        d1.mkdir()
        d2 = tmp_path / "d2"
        d2.mkdir()
        d3 = tmp_path / "d3"
        d3.mkdir()
        r1 = _make_root(d1, "confluence", "HRPRIV")
        r2 = _make_root(d2, "confluence", "ENGINEERING")
        r3 = _make_root(d3, "sharepoint", "Council")
        bl = self._blacklist_file(tmp_path)
        result = filter_blacklisted([r1, r2, r3], blacklist_file=bl)
        assert result == [r2]


# ---------------------------------------------------------------------------
# frontmatter_line_range
# ---------------------------------------------------------------------------


class TestFrontmatterLineRange:
    def test_detects_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\ntitle: Hello\npage_id: 42\n---\n\n# Body\n")
        result = frontmatter_line_range(f)
        assert result == (1, 4)

    def test_no_frontmatter_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("# Just a heading\n\nNo frontmatter.\n")
        result = frontmatter_line_range(f)
        assert result is None

    def test_unclosed_frontmatter_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\ntitle: Oops\nno closing marker\n")
        result = frontmatter_line_range(f)
        assert result is None

    def test_frontmatter_single_key(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\ntitle: X\n---\n# body\n")
        result = frontmatter_line_range(f)
        assert result == (1, 3)

    def test_empty_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\n---\n# body\n")
        result = frontmatter_line_range(f)
        assert result == (1, 2)

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = frontmatter_line_range(tmp_path / "no-such-file.md")
        assert result is None


# ---------------------------------------------------------------------------
# is_frontmatter_line
# ---------------------------------------------------------------------------


class TestIsFrontmatterLine:
    def test_line_inside_range(self) -> None:
        assert is_frontmatter_line(2, (1, 4)) is True

    def test_boundary_start(self) -> None:
        assert is_frontmatter_line(1, (1, 4)) is True

    def test_boundary_end(self) -> None:
        assert is_frontmatter_line(4, (1, 4)) is True

    def test_line_outside_range(self) -> None:
        assert is_frontmatter_line(5, (1, 4)) is False

    def test_none_range_always_false(self) -> None:
        assert is_frontmatter_line(1, None) is False
        assert is_frontmatter_line(100, None) is False
