"""Tests for mdd.confluence.paths"""

from typing import TYPE_CHECKING

from mdd.confluence.paths import disambiguate, sanitize

if TYPE_CHECKING:
    from pathlib import Path


class TestSanitize:
    def test_clean_title(self) -> None:
        assert sanitize("My Page") == "My Page"

    def test_replace_forbidden_chars(self) -> None:
        result = sanitize('A<B>C:D"E/F\\G|H?I*J')
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert '"' not in result
        assert "/" not in result
        assert "\\" not in result
        assert "|" not in result
        assert "?" not in result
        assert "*" not in result

    def test_replace_newlines_and_tabs(self) -> None:
        result = sanitize("Line\nTab\tReturn\r")
        assert "\n" not in result
        assert "\t" not in result
        assert "\r" not in result

    def test_strip_leading_trailing_dots(self) -> None:
        assert sanitize("...page...") == "page"

    def test_strip_leading_trailing_whitespace(self) -> None:
        assert sanitize("  page  ") == "page"

    def test_collapse_multiple_dashes(self) -> None:
        result = sanitize("a---b----c")
        assert result == "a-b-c"

    def test_truncate_to_200(self) -> None:
        long_title = "A" * 300
        result = sanitize(long_title)
        assert len(result) == 200

    def test_empty_fallback_untitled(self) -> None:
        assert sanitize("") == "untitled"

    def test_all_special_chars_fallback(self) -> None:
        assert sanitize("...") == "untitled"

    def test_special_chars_only_dash(self) -> None:
        # After replacing all special chars and collapsing, might end up with just dashes
        result = sanitize("<<<>>>")
        assert result  # non-empty
        assert "untitled" not in result or result == "untitled"

    def test_normal_title_preserved(self) -> None:
        assert sanitize("Architecture Decision Records") == "Architecture Decision Records"

    # --- Unicode space folding ---

    def test_nbsp_folded_to_ascii_space(self) -> None:
        # U+00A0 NO-BREAK SPACE between words, as seen in copy-pasted titles.
        title = "Malicious litellm Supply Chain Attack"
        assert sanitize(title) == "Malicious litellm Supply Chain Attack"

    def test_mixed_unicode_space_run_collapses(self) -> None:
        # A run of mixed space variants (NBSP + ASCII + em space) folds to one space.
        title = "Foo   Bar"
        assert sanitize(title) == "Foo Bar"

    def test_leading_trailing_nbsp_stripped(self) -> None:
        assert sanitize(" Page ") == "Page"

    # --- Path traversal guard ---

    def test_dot_dot_slash_neutralised(self) -> None:
        result = sanitize("../../../etc/passwd")
        assert ".." not in result
        assert "/" not in result
        assert "\\" not in result

    def test_leading_tilde_removed(self) -> None:
        result = sanitize("~/.bashrc")
        assert not result.startswith("~")

    def test_backslash_traversal_neutralised(self) -> None:
        result = sanitize("..\\..\\windows\\system32")
        assert ".." not in result
        assert "\\" not in result

    def test_traversal_result_is_non_empty(self) -> None:
        # After sanitizing a pure traversal string, result must be non-empty
        result = sanitize("../../../")
        assert result
        assert result != ""


class TestDisambiguate:
    def test_no_collision_unchanged(self, tmp_path: Path) -> None:
        path = tmp_path / "Foo.md"
        result = disambiguate(path, "12345")
        assert result == path

    def test_collision_appends_page_id(self, tmp_path: Path) -> None:
        path = tmp_path / "Foo.md"
        path.write_text("existing", encoding="utf-8")
        result = disambiguate(path, "12345")
        assert result == tmp_path / "Foo(12345).md"

    def test_collision_preserves_extension(self, tmp_path: Path) -> None:
        path = tmp_path / "Page.md"
        path.write_text("x", encoding="utf-8")
        result = disambiguate(path, "99")
        assert result.suffix == ".md"
        assert "99" in result.name

    def test_no_collision_no_file_created(self, tmp_path: Path) -> None:
        path = tmp_path / "Nonexistent.md"
        result = disambiguate(path, "42")
        assert result == path
        assert not result.exists()

    def test_double_collision_escalates_to_counter(self, tmp_path: Path) -> None:
        # Page A: Foo.md  — exists
        # Page B (titled "Foo(12345)"): also writes Foo(12345).md — exists
        # disambiguate(Foo.md, "12345") must return Foo(12345)(2).md
        path = tmp_path / "Foo.md"
        path.write_text("page A", encoding="utf-8")
        # Simulate page B already occupying the first disambiguation slot
        (tmp_path / "Foo(12345).md").write_text("page B", encoding="utf-8")
        result = disambiguate(path, "12345")
        assert result == tmp_path / "Foo(12345)(2).md"

    def test_triple_collision_escalates_further(self, tmp_path: Path) -> None:
        path = tmp_path / "Bar.md"
        path.write_text("x", encoding="utf-8")
        (tmp_path / "Bar(99).md").write_text("y", encoding="utf-8")
        (tmp_path / "Bar(99)(2).md").write_text("z", encoding="utf-8")
        result = disambiguate(path, "99")
        assert result == tmp_path / "Bar(99)(3).md"

    def test_same_page_id_in_frontmatter_returns_original(self, tmp_path: Path) -> None:
        # Incremental re-export: existing file belongs to the same page — reuse it
        path = tmp_path / "Foo.md"
        path.write_text(
            "---\nconfluence:\n  page_id: '12345'\n---\nold content\n", encoding="utf-8"
        )
        result = disambiguate(path, "12345")
        assert result == path  # no disambiguation needed

    def test_different_page_id_in_frontmatter_disambiguates(self, tmp_path: Path) -> None:
        # Existing file belongs to a different page — must disambiguate
        path = tmp_path / "Foo.md"
        path.write_text("---\nconfluence:\n  page_id: '99999'\n---\nother page\n", encoding="utf-8")
        result = disambiguate(path, "12345")
        assert result == tmp_path / "Foo(12345).md"
