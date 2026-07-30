"""Tests for scripts/sync-docs.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "sync-docs.py"


def _load_sync_docs() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sync_docs", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["sync_docs"] = module
    spec.loader.exec_module(module)
    return module


sync_docs = _load_sync_docs()

CONTENT_DOCS = ("site", "src", "content", "docs")


def write_file(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def dest_path(repo_root: Path, *parts: str) -> Path:
    return repo_root.joinpath(*CONTENT_DOCS, *parts)


def read_frontmatter(path: Path) -> dict[str, object]:
    frontmatter, _body, _consumed = sync_docs.split_frontmatter(path.read_text(encoding="utf-8"))
    return frontmatter


# --- discovery, tolerance of absent/empty source trees --------------------


def test_missing_and_empty_source_dirs_are_tolerated(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "spec" / "S01-example.md",
        "# S01: Example\n\n**Purpose:** Do a thing.\n",
    )
    (tmp_path / "docs" / "articles").mkdir(parents=True)

    assert sync_docs.run(tmp_path) == 0
    assert dest_path(tmp_path, "spec", "S01-example.md").is_file()
    assert not dest_path(tmp_path, "guide").exists()
    assert not dest_path(tmp_path, "reference").exists()


def test_spec_template_is_excluded_from_sync(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "spec" / "spec-template.md",
        "# Spec Name\n\n- [NNN-<dep>](<dep>.md) — one-line reason this is related\n",
    )
    write_file(tmp_path / "docs" / "spec" / "S01-example.md", "# S01: Example\n\n**Purpose:** X.\n")

    assert sync_docs.run(tmp_path) == 0
    assert not dest_path(tmp_path, "spec", "spec-template.md").exists()
    assert dest_path(tmp_path, "spec", "S01-example.md").is_file()


# --- frontmatter derivation: title / h1 removal ----------------------------


def test_h1_extracted_as_title_and_removed_from_body(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\nFirst paragraph text here.\n\nMore body.\n",
    )

    assert sync_docs.run(tmp_path) == 0
    dest = dest_path(tmp_path, "guide", "install.md")
    frontmatter = read_frontmatter(dest)
    body = dest.read_text(encoding="utf-8")
    assert frontmatter["title"] == "Install"
    assert "# Install" not in body
    assert "First paragraph text here." in body


def test_missing_h1_heading_is_reported_as_error(tmp_path: Path) -> None:
    write_file(tmp_path / "docs" / "guide" / "01-install.md", "No heading here, just text.\n")

    assert sync_docs.run(tmp_path) == 1
    assert not dest_path(tmp_path, "guide", "install.md").exists()


def test_existing_frontmatter_is_merged_not_clobbered(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "---\ncustom_key: keep-me\n---\n# Install\n\nBody text.\n",
    )

    assert sync_docs.run(tmp_path) == 0
    frontmatter = read_frontmatter(dest_path(tmp_path, "guide", "install.md"))
    assert frontmatter["custom_key"] == "keep-me"
    assert frontmatter["title"] == "Install"


# --- numeric-prefix stripping and sidebar order ----------------------------


def test_guide_numeric_prefix_becomes_slug_and_sidebar_order(tmp_path: Path) -> None:
    write_file(tmp_path / "docs" / "guide" / "02-quickstart.md", "# Quickstart\n\nBody text.\n")

    assert sync_docs.run(tmp_path) == 0
    dest = dest_path(tmp_path, "guide", "quickstart.md")
    assert dest.is_file()
    assert read_frontmatter(dest)["sidebar"] == {"order": 2}


def test_reference_section_supports_nested_directories(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "reference" / "cli" / "convert.md", "# convert\n\nReference body.\n"
    )

    assert sync_docs.run(tmp_path) == 0
    assert dest_path(tmp_path, "reference", "cli", "convert.md").is_file()


# --- description derivation ------------------------------------------------


def test_spec_description_comes_from_purpose_line(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "spec" / "S02-example.md",
        "# S02: Example\n\n**Purpose:** Explain the thing clearly.\n\n**Status:** Draft\n",
    )

    assert sync_docs.run(tmp_path) == 0
    frontmatter = read_frontmatter(dest_path(tmp_path, "spec", "S02-example.md"))
    assert frontmatter["description"] == "Explain the thing clearly."


def test_guide_description_comes_from_first_paragraph(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\nThis is the opening paragraph.\nStill part of it.\n\nSecond paragraph.\n",
    )

    assert sync_docs.run(tmp_path) == 0
    frontmatter = read_frontmatter(dest_path(tmp_path, "guide", "install.md"))
    assert frontmatter["description"] == "This is the opening paragraph. Still part of it."


# --- demotion frontmatter for spec/research --------------------------------


def test_spec_and_research_are_demoted_but_guide_is_not(tmp_path: Path) -> None:
    write_file(tmp_path / "docs" / "spec" / "S03-example.md", "# S03: Example\n\n**Purpose:** X.\n")
    write_file(tmp_path / "docs" / "research" / "R01-example.md", "# 001 - Example\n\nSome text.\n")
    write_file(tmp_path / "docs" / "guide" / "01-install.md", "# Install\n\nSome text.\n")

    assert sync_docs.run(tmp_path) == 0
    spec_fm = read_frontmatter(dest_path(tmp_path, "spec", "S03-example.md"))
    research_fm = read_frontmatter(dest_path(tmp_path, "research", "R01-example.md"))
    guide_fm = read_frontmatter(dest_path(tmp_path, "guide", "install.md"))

    assert spec_fm["pagefind"] is False
    assert spec_fm["sidebar"] == {"label": "S03"}
    assert "banner" in spec_fm
    assert research_fm["pagefind"] is False
    assert research_fm["sidebar"] == {"label": "R01"}
    assert "pagefind" not in guide_fm
    assert "banner" not in guide_fm
    assert guide_fm["sidebar"] == {"order": 1}


# --- link rewriting: the four cases ----------------------------------------


def test_relative_link_to_published_page_becomes_site_url(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md", "# Install\n\nSee [Safety](02-safety.md).\n"
    )
    write_file(tmp_path / "docs" / "guide" / "02-safety.md", "# Safety\n\nBe careful.\n")

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "[Safety](/mdd/guide/safety/)" in body


def test_relative_link_preserves_fragment_across_sections(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\nSee [Data protection](../spec/S07-data-protection.md#exports).\n",
    )
    write_file(
        tmp_path / "docs" / "spec" / "S07-data-protection.md",
        "# S07: Data protection\n\n**Purpose:** Protect data.\n",
    )

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "(/mdd/spec/s07-data-protection/#exports)" in body


def test_site_urls_are_lowercased_to_match_starlight_slugs(tmp_path: Path) -> None:
    """Starlight serves `S07-data-protection.md` at `.../s07-data-protection/`.

    A link that keeps the filename's case resolves to a 404 on the deployed
    site, and nothing else in the pipeline would notice: the link checker only
    asks whether the target file exists in the repository.
    """
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\nSee [S07](../spec/S07-data-protection.md) and"
        " [R14](../research/R14-documentation-strategy.md).\n",
    )
    write_file(
        tmp_path / "docs" / "spec" / "S07-data-protection.md",
        "# S07: Data protection\n\n**Purpose:** Protect data.\n",
    )
    write_file(
        tmp_path / "docs" / "research" / "R14-documentation-strategy.md",
        "# 014 - Documentation strategy\n\nA note.\n",
    )

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "(/mdd/spec/s07-data-protection/)" in body
    assert "(/mdd/research/r14-documentation-strategy/)" in body

    # The destination filename keeps its original case; only the URL is folded.
    assert dest_path(tmp_path, "spec", "S07-data-protection.md").exists()


def test_raw_markdown_twin_path_is_lowercased(tmp_path: Path) -> None:
    """A twin is fetched by URL, so its path must match the page's slug."""
    write_file(tmp_path / "docs" / "guide" / "01-Install.md", "# Install\n\nBody.\n")

    assert sync_docs.run(tmp_path) == 0
    assert (tmp_path / "site" / "public" / "guide" / "install.md").exists()


def test_relative_link_to_unpublished_file_becomes_github_url(tmp_path: Path) -> None:
    write_file(tmp_path / "README.md", "# Readme\n")
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\nSee the [README](../../README.md).\n",
    )

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert f"({sync_docs.GITHUB_BLOB_BASE}/README.md)" in body


def test_absolute_mailto_and_bare_fragment_links_are_untouched(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\n"
        "See [docs](https://example.com/x), [mail us](mailto:team@example.com), "
        "and [jump](#prerequisites).\n\n"
        "## Prerequisites\n",
    )

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "(https://example.com/x)" in body
    assert "(mailto:team@example.com)" in body
    assert "(#prerequisites)" in body


def test_broken_link_is_reported_with_original_line_number(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\nSee [missing](03-missing.md).\n",
    )

    exit_code = sync_docs.run(tmp_path)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "broken link: 03-missing.md" in captured.err
    assert "01-install.md:3:" in captured.err


# --- code-block and inline-code-span exclusion -----------------------------


def test_links_inside_fenced_code_block_are_left_alone(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\n```markdown\n[missing](03-missing.md)\n```\n\nReal text.\n",
    )

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "[missing](03-missing.md)" in body


def test_backticks_in_a_fence_candidates_info_string_do_not_open_a_fence(tmp_path: Path) -> None:
    """A backtick run followed by more backticks on the same line is an
    inline code span escaping literal backticks, not a fence — CommonMark
    disallows a backtick in a backtick-fence info string. Misreading it as a
    fence-open would swallow the rest of the file as unrewritten "code".
    """
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\n"
        "It emits ```` ```confluence-xml ```` fences around the payload.\n\n"
        "See [Safety](02-safety.md) afterward.\n",
    )
    write_file(tmp_path / "docs" / "guide" / "02-safety.md", "# Safety\n\nBe careful.\n")

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "[Safety](/mdd/guide/safety/)" in body


def test_links_inside_indented_code_block_are_left_alone(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\nSome intro paragraph.\n\n"
        "    [missing](03-missing.md)\n    more code\n\nReal text.\n",
    )

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "[missing](03-missing.md)" in body


def test_link_like_syntax_inside_inline_code_is_left_alone(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\nExample: `[missing](03-missing.md)` is literal.\n",
    )

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "`[missing](03-missing.md)`" in body


def test_list_continuation_lines_are_not_treated_as_code(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\n"
        "- Confluence: match the space key.\n"
        "- SharePoint: match the folder name, in which case\n"
        "     see [Safety](02-safety.md) for the sub-folder case.\n",
    )
    write_file(tmp_path / "docs" / "guide" / "02-safety.md", "# Safety\n\nBe careful.\n")

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "[Safety](/mdd/guide/safety/)" in body


# --- reference-style link definitions --------------------------------------


def test_reference_style_link_definition_is_rewritten(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\nSee [safety][safety-ref].\n\n[safety-ref]: 02-safety.md\n",
    )
    write_file(tmp_path / "docs" / "guide" / "02-safety.md", "# Safety\n\nBe careful.\n")

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "[safety-ref]: /mdd/guide/safety/" in body


# --- links wrapped across a line break --------------------------------------
#
# CommonMark permits a newline inside both the link text and the destination.
# A line-by-line rewriter never sees the whole link and silently leaves it
# untouched, which 404s once the destination is not the site-relative URL it
# started as.


def test_wrapped_link_text_is_rewritten(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\nSee [Safety and\nsecrets](02-safety.md) for details.\n",
    )
    write_file(tmp_path / "docs" / "guide" / "02-safety.md", "# Safety\n\nBe careful.\n")

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "[Safety and\nsecrets](/mdd/guide/safety/)" in body


def test_wrapped_link_destination_is_rewritten(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\nSee [Safety](\n02-safety.md) for details.\n",
    )
    write_file(tmp_path / "docs" / "guide" / "02-safety.md", "# Safety\n\nBe careful.\n")

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "[Safety](/mdd/guide/safety/)" in body


def test_wrapped_link_inside_fenced_code_block_is_left_alone(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\n```markdown\n[missing and\nmore](03-missing.md)\n```\n\nReal text.\n",
    )

    assert sync_docs.run(tmp_path) == 0
    body = dest_path(tmp_path, "guide", "install.md").read_text(encoding="utf-8")
    assert "[missing and\nmore](03-missing.md)" in body


def test_wrapped_broken_link_is_reported_with_correct_line_number(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_file(
        tmp_path / "docs" / "guide" / "01-install.md",
        "# Install\n\nSee [missing](\n03-missing.md) for details.\n",
    )

    exit_code = sync_docs.run(tmp_path)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "broken link: 03-missing.md" in captured.err
    assert "01-install.md:3:" in captured.err


# --- raw Markdown twins -----------------------------------------------------


def test_twin_is_written_for_non_demoted_kinds(tmp_path: Path) -> None:
    write_file(tmp_path / "docs" / "guide" / "01-install.md", "# Install\n\nBody text.\n")

    assert sync_docs.run(tmp_path) == 0
    twin = tmp_path / "site" / "public" / "guide" / "install.md"
    assert twin.is_file()
    text = twin.read_text(encoding="utf-8")
    assert text.startswith("# Install\n\nBody text.")
    assert "---" not in text.splitlines()[0]


def test_no_twin_for_spec_or_research(tmp_path: Path) -> None:
    write_file(tmp_path / "docs" / "spec" / "S01-example.md", "# S01: Example\n\n**Purpose:** X.\n")

    assert sync_docs.run(tmp_path) == 0
    assert not (tmp_path / "site" / "public" / "spec").exists()


# --- destination cleanup ----------------------------------------------------


def test_stale_destination_files_are_removed(tmp_path: Path) -> None:
    write_file(tmp_path / "docs" / "guide" / "01-install.md", "# Install\n\nBody.\n")
    assert sync_docs.run(tmp_path) == 0

    stale = dest_path(tmp_path, "guide", "stale.md")
    stale.write_text("leftover", encoding="utf-8")
    (tmp_path / "docs" / "guide" / "01-install.md").unlink()
    write_file(tmp_path / "docs" / "guide" / "02-quickstart.md", "# Quickstart\n\nBody.\n")

    assert sync_docs.run(tmp_path) == 0
    assert not stale.exists()
    assert not dest_path(tmp_path, "guide", "install.md").exists()
    assert dest_path(tmp_path, "guide", "quickstart.md").exists()


# --- pure helper functions ---------------------------------------------


def test_truncate_at_sentence_prefers_sentence_boundary() -> None:
    text = "First sentence here. " + ("word " * 40)
    assert sync_docs.truncate_at_sentence(text, limit=30) == "First sentence here."


def test_truncate_at_sentence_falls_back_to_word_boundary() -> None:
    text = ("onelongsentencewithoutanybreak " * 10).strip()
    result = sync_docs.truncate_at_sentence(text, limit=20)
    assert result.endswith("…")
    assert len(result) <= 21


def test_strip_inline_markdown_removes_code_links_and_emphasis() -> None:
    text = sync_docs.strip_inline_markdown("**Bold** and `code` and [a link](url.md)")
    assert text == "Bold and code and a link"


def test_strip_numeric_prefix() -> None:
    assert sync_docs.strip_numeric_prefix("02-quickstart") == ("quickstart", 2)
    assert sync_docs.strip_numeric_prefix("no-prefix") == ("no-prefix", None)


def test_derive_doc_id() -> None:
    assert sync_docs.derive_doc_id("S06-documentation-site") == "S06"
    assert sync_docs.derive_doc_id("000-specs") == "000"
    assert sync_docs.derive_doc_id("R14-strategy") == "R14"


def test_classify_url() -> None:
    assert sync_docs.classify_url("https://example.com") == "absolute"
    assert sync_docs.classify_url("mailto:team@example.com") == "mailto"
    assert sync_docs.classify_url("#anchor") == "fragment"
    assert sync_docs.classify_url("../spec/S01-example.md") == "relative"
