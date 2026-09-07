"""Tests for mdd.confluence.page_links — relative ``.md`` links become page links."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from mdd.confluence.create import create_page
from mdd.confluence.ir import render_confluence_storage
from mdd.confluence.page_links import resolve_page_links, split_relative_md_href
from mdd.confluence.update import update_page
from mdd.markdown.ir import parse_markdown

if TYPE_CHECKING:
    from pathlib import Path


def _render(body_md: str, md_path: Path) -> str:
    doc = resolve_page_links(parse_markdown(body_md), md_path, body_md=body_md)
    return render_confluence_storage(doc)


def _tree(tmp_path: Path) -> Path:
    """A small docs tree: docs/guide/page.md links to siblings and a parent page."""
    guide = tmp_path / "docs" / "guide"
    guide.mkdir(parents=True)
    (guide / "sibling.md").write_text("---\ntitle: Sibling Title\n---\n# Other\n", encoding="utf-8")
    (guide / "h1-only.md").write_text("# Heading Title\n\nprose\n", encoding="utf-8")
    (guide / "bare-notes.md").write_text("no heading, no frontmatter\n", encoding="utf-8")
    (tmp_path / "docs" / "index.md").write_text("---\ntitle: Docs Home\n---\n", encoding="utf-8")
    return guide / "page.md"


class TestSplitRelativeMdHref:
    @pytest.mark.parametrize(
        ("href", "expected"),
        [
            ("sibling.md", ("sibling.md", "")),
            ("../index.md", ("../index.md", "")),
            ("./a/b.md#section", ("./a/b.md", "section")),
            ("README.MD", ("README.MD", "")),
        ],
    )
    def test_relative_md_links(self, href: str, expected: tuple[str, str]) -> None:
        assert split_relative_md_href(href) == expected

    @pytest.mark.parametrize(
        "href",
        [
            "https://example.com/page.md",
            "mailto:someone@example.com",
            "/abs/path.md",
            "confluence-page:SPACE/Title",
            "image.png",
            "notes.markdown",
            "#fragment-only",
            "",
        ],
    )
    def test_everything_else_is_left_alone(self, href: str) -> None:
        assert split_relative_md_href(href) is None


class TestResolvePageLinks:
    def test_sibling_becomes_page_link_with_frontmatter_title(self, tmp_path: Path) -> None:
        md = _tree(tmp_path)
        out = _render("See [the sibling](sibling.md) now.\n", md)
        assert '<ac:link><ri:page ri:content-title="Sibling Title" />' in out
        assert "<ac:link-body>the sibling</ac:link-body></ac:link>" in out
        assert "sibling.md" not in out

    def test_parent_directory_target(self, tmp_path: Path) -> None:
        md = _tree(tmp_path)
        out = _render("[home](../index.md)\n", md)
        assert 'ri:content-title="Docs Home"' in out

    def test_fragment_becomes_anchor(self, tmp_path: Path) -> None:
        md = _tree(tmp_path)
        out = _render("[jump](sibling.md#setup-steps)\n", md)
        assert (
            '<ac:link ac:anchor="setup-steps"><ri:page ri:content-title="Sibling Title" />' in out
        )

    def test_target_title_from_h1_then_stem(self, tmp_path: Path) -> None:
        md = _tree(tmp_path)
        out = _render("[a](h1-only.md) [b](bare-notes.md)\n", md)
        assert 'ri:content-title="Heading Title"' in out
        assert 'ri:content-title="bare-notes"' in out

    def test_missing_target_is_untouched_and_warned_once(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md = _tree(tmp_path)
        body = "intro\n\nSee [gone](missing.md) and [gone again](missing.md).\n"
        with caplog.at_level(logging.WARNING):
            out = _render(body, md)
        assert '<a href="missing.md">gone</a>' in out
        warnings = [r for r in caplog.records if "missing.md" in r.getMessage()]
        assert len(warnings) == 2  # one per link occurrence, nothing swallowed
        assert f"{md}:3" in warnings[0].getMessage()

    def test_missing_target_warning_without_line_when_href_not_in_body(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md = _tree(tmp_path)
        body = "[gone](missing.md)\n"
        doc = parse_markdown(body)
        with caplog.at_level(logging.WARNING):
            resolve_page_links(doc, md)  # no body_md → no line lookup
        msg = caplog.records[-1].getMessage()
        assert msg.startswith(f"{md}: ")
        assert "missing.md" in msg

    def test_unreadable_target_is_untouched_and_warned(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md = _tree(tmp_path)
        with (
            patch("mdd.confluence.page_links.read_frontmatter", side_effect=OSError("denied")),
            caplog.at_level(logging.WARNING),
        ):
            out = _render("[s](sibling.md)\n", md)
        assert '<a href="sibling.md">s</a>' in out
        assert any("denied" in r.getMessage() for r in caplog.records)

    def test_absolute_and_confluence_uris_pass_through(self, tmp_path: Path) -> None:
        md = _tree(tmp_path)
        body = (
            "[web](https://example.com/x.md) "
            "[mail](mailto:a@b.c) "
            "[root](/docs/sibling.md) "
            "[page](confluence-page:SPACE/Existing%20Page)\n"
        )
        out = _render(body, md)
        assert '<a href="https://example.com/x.md">web</a>' in out
        assert '<a href="mailto:a@b.c">mail</a>' in out
        assert '<a href="/docs/sibling.md">root</a>' in out
        assert '<ri:page ri:content-title="Existing Page" ri:space-key="SPACE" />' in out

    def test_code_span_and_code_block_are_not_links(self, tmp_path: Path) -> None:
        md = _tree(tmp_path)
        body = "Use `[x](sibling.md)` literally.\n\n```\n[y](sibling.md)\n```\n"
        out = _render(body, md)
        assert "ri:page" not in out
        assert "[x](sibling.md)" in out

    def test_links_nested_in_emphasis_and_lists_and_tables(self, tmp_path: Path) -> None:
        md = _tree(tmp_path)
        body = (
            "**bold [s](sibling.md)** and *em [h](h1-only.md)*\n\n"
            "- item [i](sibling.md)\n\n"
            "| a |\n|---|\n| [t](../index.md) |\n"
        )
        out = _render(body, md)
        assert out.count('ri:content-title="Sibling Title"') == 2
        assert 'ri:content-title="Heading Title"' in out
        assert 'ri:content-title="Docs Home"' in out

    def test_target_title_is_read_once_per_file(self, tmp_path: Path) -> None:
        md = _tree(tmp_path)
        body = "[a](sibling.md) [b](sibling.md) [c](./sibling.md)\n"
        with patch(
            "mdd.confluence.page_links.read_frontmatter",
            return_value=({"title": "Cached"}, ""),
        ) as reader:
            out = _render(body, md)
        assert out.count('ri:content-title="Cached"') == 3
        assert reader.call_count == 1


# ---------------------------------------------------------------------------
# End to end through create_page / update_page, and the --no-resolve-links flag
# ---------------------------------------------------------------------------


def _make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.url = "https://example.atlassian.net"
    cfg.username = "user@example.com"
    cfg.api_token = "tok"
    return cfg


def _make_client() -> MagicMock:
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get_space.return_value = {"id": "SPACE1"}
    client.post_page.return_value = {"id": "42", "title": "x", "status": "current"}
    client.get_page.return_value = {
        "id": "42",
        "title": "x",
        "version": {"number": 1},
        "body": {"storage": {"value": "<p>remote content</p>"}},
    }
    client.put_page.return_value = {
        "id": "42",
        "title": "x",
        "status": "current",
        "version": {"number": 2, "authorId": "uid1", "createdAt": "2024-01-01T00:00:00Z"},
    }
    client.get_user.return_value = {"displayName": "Alice"}
    return client


class TestCreateAndUpdateFlag:
    def test_create_resolves_by_default(self, tmp_path: Path) -> None:
        md = _tree(tmp_path)
        md.write_text("# Page\n\n[s](sibling.md)\n", encoding="utf-8")
        client = _make_client()
        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            assert create_page(md, _make_config(), space_key="S") == 0
        assert 'ri:content-title="Sibling Title"' in client.put_page.call_args.args[2]

    def test_create_flag_off_leaves_href(self, tmp_path: Path) -> None:
        md = _tree(tmp_path)
        md.write_text("# Page\n\n[s](sibling.md)\n", encoding="utf-8")
        client = _make_client()
        with (
            patch("mdd.confluence.create.ConfluenceClient", return_value=client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            assert create_page(md, _make_config(), space_key="S", resolve_links=False) == 0
        assert '<a href="sibling.md">s</a>' in client.put_page.call_args.args[2]

    def test_update_resolves_by_default(self, tmp_path: Path) -> None:
        md = _tree(tmp_path)
        md.write_text(
            "---\nconfluence:\n  page_id: '42'\n  version: 1\n---\n# Page\n\n[s](sibling.md)\n",
            encoding="utf-8",
        )
        client = _make_client()
        with patch("mdd.confluence.update.ConfluenceClient", return_value=client):
            assert update_page(md, _make_config(), yes=True) == 0
        assert 'ri:content-title="Sibling Title"' in client.put_page.call_args.args[2]

    def test_update_flag_off_leaves_href(self, tmp_path: Path) -> None:
        md = _tree(tmp_path)
        md.write_text(
            "---\nconfluence:\n  page_id: '42'\n  version: 1\n---\n# Page\n\n[s](sibling.md)\n",
            encoding="utf-8",
        )
        client = _make_client()
        with patch("mdd.confluence.update.ConfluenceClient", return_value=client):
            assert update_page(md, _make_config(), yes=True, resolve_links=False) == 0
        assert '<a href="sibling.md">s</a>' in client.put_page.call_args.args[2]
