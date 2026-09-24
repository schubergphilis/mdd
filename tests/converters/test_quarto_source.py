"""Tests for mdd.converters.quarto_source."""

from __future__ import annotations

from mdd.converters.quarto_source import prepare_quarto_source
from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter


def _frontmatter(text: str) -> dict[str, object]:
    split = split_frontmatter(text)
    assert split is not None
    mapping = parse_yaml_mapping(split[0])
    assert mapping is not None
    return dict(mapping)


class TestFrontmatterAllowList:
    def test_presentation_keys_survive(self) -> None:
        src = (
            "---\n"
            "title: Report\n"
            "subtitle: Q3\n"
            "author: Someone\n"
            "date: today\n"
            "toc: true\n"
            "format:\n"
            "  docx:\n"
            "    reference-doc: ref.docx\n"
            "    toc: true\n"
            "---\n"
            "# Body\n"
        )
        prepared = prepare_quarto_source(src)
        fm = _frontmatter(prepared.text)
        assert fm == {
            "title": "Report",
            "subtitle": "Q3",
            "author": "Someone",
            "date": "today",
            "toc": True,
            "format": {"docx": {"reference-doc": "ref.docx", "toc": True}},
        }
        assert prepared.dropped_keys == []
        assert prepared.text.endswith("---\n# Body\n")

    def test_execution_keys_dropped_and_reported(self) -> None:
        src = (
            "---\n"
            "title: Report\n"
            "filters: [/tmp/evil.lua]\n"
            "metadata-files: [/etc/secret.yaml]\n"
            "bibliography: refs.bib\n"
            "include-before-body: x.tex\n"
            "---\n"
            "body\n"
        )
        prepared = prepare_quarto_source(src)
        fm = _frontmatter(prepared.text)
        assert fm == {"title": "Report"}
        assert prepared.dropped_keys == [
            "filters",
            "metadata-files",
            "bibliography",
            "include-before-body",
        ]

    def test_format_level_execution_keys_dropped(self) -> None:
        src = (
            "---\nformat:\n  docx:\n    filters: [x.lua]\n    toc: true\n  pptx: default\n---\n"
            "body\n"
        )
        prepared = prepare_quarto_source(src)
        fm = _frontmatter(prepared.text)
        assert fm == {"format": {"docx": {"toc": True}, "pptx": "default"}}
        assert prepared.dropped_keys == ["format.docx.filters"]

    def test_tool_owned_blocks_dropped_silently(self) -> None:
        src = (
            "---\n"
            "sharepoint:\n  sync:\n    update_office: true\n"
            "confluence:\n  page_id: '1'\n"
            "publish_office:\n  formats: [docx]\n"
            "pptx:\n  slide_count: 3\n"
            "---\n"
            "body\n"
        )
        prepared = prepare_quarto_source(src)
        assert prepared.text == "body\n"
        assert prepared.dropped_keys == []

    def test_all_keys_dropped_yields_body_only(self) -> None:
        prepared = prepare_quarto_source("---\nfilters: [x]\n---\nbody\n")
        assert prepared.text == "body\n"
        assert prepared.dropped_keys == ["filters"]

    def test_unparseable_frontmatter_is_dropped(self) -> None:
        prepared = prepare_quarto_source("---\n- just\n- a list\n---\nbody\n")
        assert prepared.text == "body\n"

    def test_shortcodes_in_metadata_strings_are_escaped(self) -> None:
        src = (
            "---\ntitle: '{{< include /etc/passwd >}}'\nauthor:\n  - name: '{{< meta x >}}'\n---\n"
        )
        prepared = prepare_quarto_source(src)
        fm = _frontmatter(prepared.text)
        assert fm["title"] == "{{{< include /etc/passwd >}}}"
        assert fm["author"] == [{"name": "{{{< meta x >}}}"}]


class TestBody:
    def test_mid_document_yaml_block_is_neutralised(self) -> None:
        src = "Intro\n\n---\nfilters: [/tmp/evil.lua]\n---\n\nMore\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == "Intro\n\n***\nfilters: [/tmp/evil.lua]\n***\n\nMore\n"

    def test_delimiter_with_trailing_whitespace_and_crlf(self) -> None:
        prepared = prepare_quarto_source("a\r\n--- \r\nb\r\n")
        assert prepared.text == "a\r\n***\r\nb\r\n"

    def test_delimiter_inside_code_fence_is_left_alone(self) -> None:
        src = "```yaml\n---\nkey: value\n---\n```\n\n---\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == "```yaml\n---\nkey: value\n---\n```\n\n***\n"

    def test_tilde_fence_and_longer_closing_fence(self) -> None:
        src = "~~~\n---\n~~~~\n---\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == "~~~\n---\n~~~~\n***\n"

    def test_backtick_fence_with_backtick_in_info_string_is_not_a_fence(self) -> None:
        src = "``` a`b\n---\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == "``` a`b\n***\n"

    def test_unclosed_fence_swallows_rest(self) -> None:
        src = "```\n---\nstill code\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == src

    def test_include_shortcode_is_escaped(self) -> None:
        src = "Hello {{< include ../../secret.md >}} world\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == "Hello {{{< include ../../secret.md >}}} world\n"

    def test_shortcode_inside_code_fence_is_left_alone(self) -> None:
        src = "```\n{{< include x >}}\n```\n"
        assert prepare_quarto_source(src).text == src

    def test_plain_markdown_is_unchanged(self) -> None:
        src = "# Title\n\nSome *text* with a [link](http://x) and `code`.\n\n- a\n- b\n"
        assert prepare_quarto_source(src).text == src

    def test_body_starting_with_delimiter_after_frontmatter(self) -> None:
        src = "---\ntitle: T\n---\n---\nfilters: [x]\n---\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == "---\ntitle: T\n---\n***\nfilters: [x]\n***\n"
