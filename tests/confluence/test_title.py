"""Tests for mdd.confluence.title — the shared page-title rule."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdd.confluence.title import first_h1, frontmatter_title, resolve_page_title

_MD = Path("/docs/getting-started.md")


class TestFirstH1:
    def test_returns_first_h1_text(self) -> None:
        assert first_h1("intro\n\n# Title One\n\n# Title Two\n") == "Title One"

    def test_none_when_no_h1(self) -> None:
        assert first_h1("## Only an H2\n\nprose\n") is None

    def test_strips_surrounding_whitespace(self) -> None:
        assert first_h1("#   Spaced Out   \n") == "Spaced Out"


class TestFrontmatterTitle:
    def test_non_empty_string(self) -> None:
        assert frontmatter_title({"title": "  Getting started  "}) == "Getting started"

    @pytest.mark.parametrize("raw", ["", "   ", None, 2026, ["a"], {"x": 1}])
    def test_non_string_or_blank_is_ignored(self, raw: object) -> None:
        assert frontmatter_title({"title": raw}) is None

    def test_missing_key(self) -> None:
        assert frontmatter_title({"confluence": {"title": "Stale mirror title"}}) is None


class TestResolvePageTitle:
    def test_cli_flag_wins_over_everything(self) -> None:
        title = resolve_page_title({"title": "FM"}, "# H1\n", _MD, cli_title="Flag")
        assert title == "Flag"

    def test_frontmatter_title_beats_h1(self) -> None:
        assert resolve_page_title({"title": "FM"}, "# H1\n", _MD) == "FM"

    def test_h1_when_no_frontmatter_title(self) -> None:
        assert resolve_page_title({}, "# H1\n\nbody\n", _MD) == "H1"

    def test_h1_when_frontmatter_title_blank(self) -> None:
        assert resolve_page_title({"title": ""}, "# H1\n", _MD) == "H1"

    def test_confluence_block_title_is_not_consulted(self) -> None:
        fm = {"confluence": {"title": "Old exported title"}}
        assert resolve_page_title(fm, "# H1\n", _MD) == "H1"

    def test_stem_when_nothing_else(self) -> None:
        assert resolve_page_title({}, "just prose\n", _MD) == "getting-started"

    def test_empty_cli_flag_falls_through(self) -> None:
        assert resolve_page_title({}, "# H1\n", _MD, cli_title="") == "H1"
