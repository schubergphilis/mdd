"""Tests for mdd.converters.quarto_source."""

from __future__ import annotations

import random
import re
import time

import pytest

from mdd.converters.quarto_source import (
    _backtick_fence_spans,  # pyright: ignore[reportPrivateUsage]
    _html_comment_spans,  # pyright: ignore[reportPrivateUsage]
    prepare_quarto_source,
)
from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter

_FILTER_BLOCK = "---\nfilters: [/tmp/evil.lua]\n---\n"
_NEUTRALISED_BLOCK = "***\nfilters: [/tmp/evil.lua]\n---\n"


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
            "    slide-level: 2\n"
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
            "format": {"docx": {"slide-level": 2, "toc": True}},
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

    def test_format_level_file_keys_dropped(self) -> None:
        src = (
            "---\nformat:\n  docx:\n    filters: [x.lua]\n    reference-doc: /tmp/x.docx\n"
            "    toc: true\n  pptx: default\n---\nbody\n"
        )
        prepared = prepare_quarto_source(src)
        fm = _frontmatter(prepared.text)
        assert fm == {"format": {"docx": {"toc": True}, "pptx": "default"}}
        assert prepared.dropped_keys == ["format.docx.filters", "format.docx.reference-doc"]

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

    def test_frontmatter_after_blank_lines_is_treated_as_body_block(self) -> None:
        """Quarto trims leading blank lines before looking for frontmatter; mdd does not."""
        prepared = prepare_quarto_source("\n\n" + _FILTER_BLOCK + "body\n")
        assert prepared.text == "\n\n" + _NEUTRALISED_BLOCK + "body\n"

    def test_leading_byte_order_mark_is_dropped(self) -> None:
        prepared = prepare_quarto_source("\ufeff---\ntitle: T\nfilters: [x]\n---\nbody\n")
        assert prepared.text == "---\ntitle: T\n---\nbody\n"
        assert prepared.dropped_keys == ["filters"]

    def test_crlf_frontmatter_is_parsed(self) -> None:
        prepared = prepare_quarto_source("---\r\ntitle: T\r\nfilters: [x]\r\n---\r\nbody\r\n")
        assert prepared.text == "---\ntitle: T\n---\nbody\n"
        assert prepared.dropped_keys == ["filters"]


class TestExtraMetadata:
    def test_extra_metadata_is_added_after_the_filter(self) -> None:
        prepared = prepare_quarto_source(
            "---\ntitle: T\nfilters: [evil.lua]\n---\nbody\n",
            extra_metadata={"filters": ["/opt/mdd/guard.lua"]},
        )
        assert prepared.text == "---\ntitle: T\nfilters:\n- /opt/mdd/guard.lua\n---\nbody\n"
        assert prepared.dropped_keys == ["filters"]

    def test_extra_metadata_creates_frontmatter(self) -> None:
        prepared = prepare_quarto_source("body\n", extra_metadata={"filters": ["g.lua"]})
        assert prepared.text == "---\nfilters:\n- g.lua\n---\nbody\n"

    def test_extra_metadata_is_not_rewritten(self) -> None:
        prepared = prepare_quarto_source("body\n", extra_metadata={"x": "&amp;"})
        assert _frontmatter(prepared.text) == {"x": "&amp;"}


class TestMetadataStrings:
    def test_shortcodes_in_metadata_strings_are_escaped(self) -> None:
        src = (
            "---\ntitle: '{{< include /etc/passwd >}}'\nauthor:\n  - name: '{{< meta x >}}'\n---\n"
        )
        prepared = prepare_quarto_source(src)
        fm = _frontmatter(prepared.text)
        assert fm["title"] == "{{{< include /etc/passwd >}}}"
        assert fm["author"] == [{"name": "{{{< meta x >}}}"}]

    @pytest.mark.parametrize(
        "spelling",
        [
            "{{&lt; env HOME &gt;}}",
            "{{&#60; env HOME &#62;}}",
            "&#123;{< env HOME >}}",
            "{{\\< env HOME \\>}}",
            "\\{\\{< env HOME >\\}\\}",
            "&amp;#123;&amp;#123;&amp;lt; env HOME &amp;gt;&amp;#125;&amp;#125;",
            "&amp;#123;{< env HOME >}}",
            "\\&#123;\\&#123;\\&lt; env HOME \\&gt;\\&#125;\\&#125;",
            "\\\\{\\\\{\\\\< env HOME \\\\>\\\\}\\\\}",
            "&#92;{&#92;{&#92;< env HOME &#92;>&#92;}&#92;}",
            "&#123;&#123;&lt; env HOME &gt;&#125;&#125;",
            "&amp;amp;amp;#123;{< env HOME >}}",
        ],
    )
    def test_entity_and_backslash_spellings_in_metadata_are_escaped(self, spelling: str) -> None:
        """Pandoc reads metadata as Markdown, so encoded delimiters would become ``{{<``."""
        prepared = prepare_quarto_source(f"---\ntitle: '{spelling}'\n---\nbody\n")
        assert _frontmatter(prepared.text)["title"] == "{{{< env HOME >}}}"

    def test_plain_entities_in_metadata_are_decoded_only(self) -> None:
        prepared = prepare_quarto_source("---\ntitle: 'Q &amp; A &lt;3'\n---\nbody\n")
        assert _frontmatter(prepared.text)["title"] == "Q & A <3"

    def test_double_encoded_plain_text_decodes_to_what_pandoc_would_show(self) -> None:
        prepared = prepare_quarto_source("---\ntitle: 'Q &amp;amp; A'\n---\nbody\n")
        assert _frontmatter(prepared.text)["title"] == "Q & A"

    def test_deeply_nested_encoding_loses_its_escape_characters(self) -> None:
        """A string still decoding after many passes keeps no ``&`` or backslash for pandoc."""
        nested = "&amp;" + "amp;" * 20 + "lt;{< env HOME >}} \\x"
        prepared = prepare_quarto_source(f"---\ntitle: '{nested}'\n---\nbody\n")
        title = _frontmatter(prepared.text)["title"]
        assert isinstance(title, str)
        assert "&" not in title
        assert "\\" not in title
        assert "{{<" not in title.replace("{{{<", "")
        assert title.endswith("{< env HOME >}}} x")

    def test_non_string_scalars_pass_through(self) -> None:
        prepared = prepare_quarto_source("---\ntitle: 5\ntoc: true\ntoc-depth: 2\n---\nbody\n")
        assert _frontmatter(prepared.text) == {"title": 5, "toc": True, "toc-depth": 2}


class TestBodyYamlBlocks:
    def test_mid_document_yaml_block_opener_is_neutralised(self) -> None:
        src = "Intro\n\n" + _FILTER_BLOCK + "\nMore\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == "Intro\n\n" + _NEUTRALISED_BLOCK + "\nMore\n"

    def test_block_directly_after_paragraph_is_neutralised(self) -> None:
        """Quarto does not require a blank line before a metadata block."""
        prepared = prepare_quarto_source("Intro\n" + _FILTER_BLOCK)
        assert prepared.text == "Intro\n" + _NEUTRALISED_BLOCK

    def test_dots_terminator_is_a_block(self) -> None:
        prepared = prepare_quarto_source("Intro\n\n---\nfilters: [x]\n...\n")
        assert prepared.text == "Intro\n\n***\nfilters: [x]\n...\n"

    def test_opener_with_trailing_whitespace_and_crlf(self) -> None:
        prepared = prepare_quarto_source("a\r\n--- \r\nfilters: [x]\r\n---\r\nb\r\n")
        assert prepared.text == "a\n*** \nfilters: [x]\n---\nb\n"

    @pytest.mark.parametrize("terminator", ["\r", "\u2028", "\u2029"])
    def test_other_line_terminators_start_a_line(self, terminator: str) -> None:
        prepared = prepare_quarto_source(f"Intro{terminator}" + _FILTER_BLOCK)
        assert prepared.text == "Intro\n" + _NEUTRALISED_BLOCK

    def test_consecutive_blocks_are_all_neutralised(self) -> None:
        src = "---\na: 1\n---\nb: 2\n---\nc: 3\n---\n"
        prepared = prepare_quarto_source("x\n" + src)
        assert prepared.text == "x\n***\na: 1\n***\nb: 2\n***\nc: 3\n---\n"

    def test_lone_rule_without_closer_is_left_alone(self) -> None:
        src = "a\n\n---\n\nb\n"
        assert prepare_quarto_source(src).text == src

    def test_setext_heading_is_left_alone(self) -> None:
        """A ``---`` followed by a blank line is never a metadata block."""
        src = "My Heading\n---\n\nbody\n"
        assert prepare_quarto_source(src).text == src

    def test_indented_delimiter_is_not_an_opener(self) -> None:
        src = "a\n\n ---\nfilters: [x]\n---\n"
        assert prepare_quarto_source(src).text == src

    def test_body_starting_with_delimiter_after_frontmatter(self) -> None:
        src = "---\ntitle: T\n---\n---\nfilters: [x]\n---\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == "---\ntitle: T\n---\n***\nfilters: [x]\n---\n"

    def test_plain_markdown_is_unchanged(self) -> None:
        src = "# Title\n\nSome *text* with a [link](http://x) and `code`.\n\n- a\n- b\n"
        assert prepare_quarto_source(src).text == src


class TestBodyFences:
    """Quarto's scanner only treats same-prefix backtick fences as code."""

    def test_delimiters_inside_backtick_fence_are_left_alone(self) -> None:
        src = "```yaml\n---\nkey: value\n---\n```\n\n---\n"
        assert prepare_quarto_source(src).text == src

    def test_fence_with_matching_blockquote_prefix_is_code(self) -> None:
        src = "> ```\n> ---\n> filters: [x]\n> ---\n> ```\n"
        assert prepare_quarto_source(src).text == src

    def test_fence_with_indented_prefix_is_code_when_closer_matches(self) -> None:
        src = " ```\n---\nfilters: [x]\n---\n ```\n"
        assert prepare_quarto_source(src).text == src

    @pytest.mark.parametrize(
        ("name", "src", "expected"),
        [
            (
                "tilde fence",
                "~~~\n---\nfilters: [x]\n---\n~~~\n",
                "~~~\n***\nfilters: [x]\n---\n~~~\n",
            ),
            (
                "fence in list item",
                "- ```\n  code\n  ```\n\n" + _FILTER_BLOCK,
                "- ```\n  code\n  ```\n\n" + _NEUTRALISED_BLOCK,
            ),
            (
                "fence in ordered list item",
                "1. ```\n   code\n   ```\n\n" + _FILTER_BLOCK,
                "1. ```\n   code\n   ```\n\n" + _NEUTRALISED_BLOCK,
            ),
            (
                "closer indented differently",
                "```\ncode\n    ```\n\n" + _FILTER_BLOCK,
                "```\ncode\n    ```\n\n" + _NEUTRALISED_BLOCK,
            ),
            (
                "opener indented, closer not",
                " ```\n---\nfilters: [x]\n---\n```\n",
                " ```\n***\nfilters: [x]\n---\n```\n",
            ),
            (
                "closer shorter than opener",
                "````\ncode\n```\n\n" + _FILTER_BLOCK,
                "````\ncode\n```\n\n" + _NEUTRALISED_BLOCK,
            ),
            (
                "backtick in info string",
                "``` a`b\n---\nfilters: [x]\n---\n```\n",
                "``` a`b\n***\nfilters: [x]\n---\n```\n",
            ),
            (
                "unclosed fence",
                "```\n---\nfilters: [x]\n---\n",
                "```\n***\nfilters: [x]\n---\n",
            ),
            (
                "closer followed by a character Python calls whitespace but JavaScript does not",
                "```\n---\nfilters: [x]\n---\n```\x85\n",
                "```\n***\nfilters: [x]\n---\n```\x85\n",
            ),
            (
                "fence inside html comment",
                "<!--\n```\n-->\n\n" + _FILTER_BLOCK,
                "<!--\n```\n-->\n\n" + _NEUTRALISED_BLOCK,
            ),
            (
                "fence inside pre block",
                "<pre>\n```\n</pre>\n\n" + _FILTER_BLOCK,
                "<pre>\n```\n</pre>\n\n" + _NEUTRALISED_BLOCK,
            ),
            (
                "fence inside display math",
                "$$\n```\n$$\n\n" + _FILTER_BLOCK,
                "$$\n```\n$$\n\n" + _NEUTRALISED_BLOCK,
            ),
        ],
    )
    def test_shapes_quarto_does_not_treat_as_code(self, name: str, src: str, expected: str) -> None:
        assert prepare_quarto_source(src).text == expected, name


class TestBodyHtmlComments:
    """Quarto strips HTML comments before scanning, which can join lines."""

    def test_opener_formed_by_comment_removal(self) -> None:
        src = "Intro\n\n<!--\n-->---\nfilters: [x]\n...\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == "Intro\n\n<!--\n-->***\nfilters: [x]\n...\n"

    def test_opener_with_trailing_comment(self) -> None:
        src = "Intro\n\n---<!-- x -->\nfilters: [x]\n...\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == "Intro\n\n***<!-- x -->\nfilters: [x]\n...\n"

    def test_opener_split_by_comment(self) -> None:
        src = "Intro\n\n-<!-- x -->--\nfilters: [x]\n...\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == "Intro\n\n*<!-- x -->**\nfilters: [x]\n...\n"

    def test_block_entirely_inside_comment_is_left_alone(self) -> None:
        src = "<!--\n" + _FILTER_BLOCK + "-->\n"
        assert prepare_quarto_source(src).text == src


class TestBodyShortcodes:
    def test_include_shortcode_is_escaped(self) -> None:
        src = "Hello {{< include ../../secret.md >}} world\n"
        prepared = prepare_quarto_source(src)
        assert prepared.text == "Hello {{{< include ../../secret.md >}}} world\n"

    def test_shortcode_without_inner_spaces_is_escaped(self) -> None:
        assert prepare_quarto_source("{{<env HOME>}}\n").text == "{{{<env HOME>}}}\n"

    def test_shortcode_spanning_lines_is_escaped(self) -> None:
        assert prepare_quarto_source("{{<\nenv HOME\n>}}\n").text == "{{{<\nenv HOME\n>}}}\n"

    @pytest.mark.parametrize(
        "src",
        [
            "```\n{{< env HOME >}}\n```\n",
            "~~~\n{{< env HOME >}}\n~~~\n",
            "Hello `{{< env HOME >}}` world\n",
            "- ```\n  code\n  ```\n\n{{< env HOME >}}\n",
        ],
    )
    def test_shortcodes_are_escaped_inside_code_too(self, src: str) -> None:
        """Quarto expands shortcodes in code blocks and inline code as well."""
        assert prepare_quarto_source(src).text == src.replace("{{<", "{{{<").replace(">}}", ">}}}")


# The expressions Quarto itself uses to strip HTML comments and backtick fences
# before looking for YAML blocks. The scanners in the module must find exactly
# the same spans.
_JS_WHITESPACE = r"\t\n\v\f\r    -     　﻿"
_REFERENCE_COMMENT_RE = re.compile(r"<!--[\W\w]*?-->")
_REFERENCE_FENCE_RE = re.compile(
    r"^([\t >]*`{3,})[^`\n]*\n[\W\w]*?\n\1[" + _JS_WHITESPACE + r"]*$", re.MULTILINE
)
_TOKENS = [
    "```",
    "````",
    "`",
    "\n",
    "\n",
    "\n",
    " ",
    "  ",
    "\t",
    ">",
    "<!--",
    "-->",
    "--",
    "-",
    "<!",
    "a",
    "---",
    "...",
    " ",
    "\x85",
    "\v",
]


def _reference_spans(pattern: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    return [m.span() for m in pattern.finditer(text)]


class TestScannersMatchQuartoExpressions:
    def test_random_inputs(self) -> None:
        rng = random.Random(20260924)  # noqa: S311 - reproducible test inputs
        for _ in range(5000):
            text = "".join(rng.choice(_TOKENS) for _ in range(rng.randint(0, 30)))
            assert _html_comment_spans(text) == _reference_spans(_REFERENCE_COMMENT_RE, text), repr(
                text
            )
            assert _backtick_fence_spans(text) == _reference_spans(_REFERENCE_FENCE_RE, text), repr(
                text
            )

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "```\n",
            "```\n```",
            "```\n\n```",
            "```\nx\n```",
            "```\nx\n```\n",
            "```\nx\n``` \n\n  \nnext",
            "```\nx\n```\n \n",
            "> ```\n> x\n> ```\n",
            "```\n```\n```\n```\n",
            "<!-->-->",
            "<!--<!-- -->-->",
        ],
    )
    def test_edge_cases(self, text: str) -> None:
        assert _html_comment_spans(text) == _reference_spans(_REFERENCE_COMMENT_RE, text)
        assert _backtick_fence_spans(text) == _reference_spans(_REFERENCE_FENCE_RE, text)


class TestLargeInputs:
    @pytest.mark.parametrize("unit", ["<!--\n", "```a\nx\n", "> ```\n", "---\nx\n"])
    def test_preparation_time_grows_slowly(self, unit: str) -> None:
        """Unclosed openers are each looked at once, not rescanned to the end of the text."""
        body = "# t\n\n" + unit * (500_000 // len(unit))
        started = time.perf_counter()
        prepare_quarto_source(body)
        assert time.perf_counter() - started < 10
