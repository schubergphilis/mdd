"""Tests for the shared line/span classifier."""

from __future__ import annotations

from mdd.prose.classify import (
    Classified,
    ClassifyError,
    LineClass,
    classify,
    join_lines,
    split_lines,
)


def ok(text: str) -> Classified:
    result = classify(text)
    assert isinstance(result, Classified)
    return result


def classes(text: str) -> list[LineClass]:
    return [line.cls for line in ok(text).lines]


def test_split_and_join_round_trip() -> None:
    for text in ("a\nb\n", "a\nb", "", "\n", "a\r\nb\r\n"):
        lines, newline, final = split_lines(text)
        assert join_lines(lines, newline, final_newline=final) == text


def test_frontmatter_then_prose() -> None:
    assert classes("---\na: 1\n---\n\nBody.\n") == [
        LineClass.FRONTMATTER,
        LineClass.FRONTMATTER,
        LineClass.FRONTMATTER,
        LineClass.BLANK,
        LineClass.PROSE,
    ]


def test_unclosed_frontmatter_fails_closed() -> None:
    result = classify("---\na: 1\nstill going\n")
    assert isinstance(result, ClassifyError)
    assert result.line == 1
    assert "frontmatter" in result.reason


def test_unclosed_fence_fails_closed() -> None:
    result = classify("Prose.\n\n```\ncode\n")
    assert isinstance(result, ClassifyError)
    assert result.line == 3


def test_unclosed_comment_fails_closed() -> None:
    result = classify("<!--\nnever closed\n")
    assert isinstance(result, ClassifyError)
    assert "comment" in result.reason


def test_unclosed_math_fails_closed() -> None:
    result = classify("$$\nx = 1\n")
    assert isinstance(result, ClassifyError)
    assert "math" in result.reason


def test_fence_of_tildes_closes_on_tildes_only() -> None:
    assert classes("~~~\n```\n~~~\n") == [LineClass.FENCED_CODE] * 3


def test_indented_code_only_after_a_blank_line() -> None:
    assert classes("Prose.\n\n    code\n") == [
        LineClass.PROSE,
        LineClass.BLANK,
        LineClass.INDENTED_CODE,
    ]


def test_list_continuation_is_not_indented_code() -> None:
    result = ok("- item\n  continuation\n")
    assert [line.cls for line in result.lines] == [LineClass.PROSE, LineClass.PROSE]
    assert result.lines[0].block == result.lines[1].block


def test_list_prefix_and_continuation_prefix() -> None:
    line = ok("- item\n").lines[0]
    assert line.prefix == "- "
    assert line.cont_prefix == "  "
    assert line.content == "item"


def test_block_quote_prefix_is_preserved() -> None:
    line = ok("> quoted\n").lines[0]
    assert line.prefix == "> "
    assert line.cont_prefix == "> "


def test_empty_block_quote_line() -> None:
    assert classes(">\n") == [LineClass.BLOCK_QUOTE]


def test_table_header_and_body_are_table() -> None:
    assert classes("| a | b |\n|---|---|\n| 1 | 2 |\nafter\n") == [
        LineClass.TABLE,
        LineClass.TABLE,
        LineClass.TABLE,
        LineClass.PROSE,
    ]


def test_setext_heading_absorbs_its_paragraph() -> None:
    assert classes("Title\n=====\n\nBody.\n") == [
        LineClass.HEADING,
        LineClass.HEADING,
        LineClass.BLANK,
        LineClass.PROSE,
    ]


def test_thematic_break_is_not_prose() -> None:
    assert classes("Prose.\n\n***\n") == [
        LineClass.PROSE,
        LineClass.BLANK,
        LineClass.THEMATIC_BREAK,
    ]


def test_link_reference_definition() -> None:
    assert classes("[label]: https://example.com\n") == [LineClass.LINK_DEF]


def test_html_block_ends_at_a_blank_line() -> None:
    assert classes("<div>\nraw\n\nProse.\n") == [
        LineClass.HTML_BLOCK,
        LineClass.HTML_BLOCK,
        LineClass.BLANK,
        LineClass.PROSE,
    ]


def test_single_line_comment_does_not_open_a_block() -> None:
    assert classes("<!-- x -->\nProse.\n") == [LineClass.HTML_COMMENT, LineClass.PROSE]


def test_single_line_math_does_not_open_a_block() -> None:
    assert classes("$$ x = 1 $$\nProse.\n") == [LineClass.MATH, LineClass.PROSE]


def test_hard_break_is_recorded() -> None:
    lines = ok("a  \nb\n").lines
    assert lines[0].hard_break
    assert not lines[1].hard_break


def test_masks_cover_inline_code_but_not_code_blocks() -> None:
    prose = ok("a `b c` d\n").lines[0]
    assert [(s.start, s.end) for s in prose.masks] == [(2, 7)]
    fenced = ok("```\na `b` c\n```\n").lines[1]
    assert fenced.masks == ()


def test_blocks_break_at_a_blank_line() -> None:
    lines = ok("one\ntwo\n\nthree\n").lines
    assert lines[0].block == lines[1].block
    assert lines[3].block != lines[0].block


def test_callout_marker_is_not_joined_into_the_paragraph() -> None:
    lines = ok("> [!WARNING]\n> Body text.\n").lines
    assert lines[0].cls is LineClass.MANAGED
    assert lines[1].cls is LineClass.PROSE


def test_confluence_export_callout_is_managed() -> None:
    text = "> **Confluence export**\n>\n> This page was exported.\n\nBody.\n"
    assert classes(text) == [
        LineClass.MANAGED,
        LineClass.MANAGED,
        LineClass.MANAGED,
        LineClass.BLANK,
        LineClass.PROSE,
    ]


def test_sharepoint_export_callout_is_managed() -> None:
    assert classes("> **SharePoint export**\n> details\n")[0] is LineClass.MANAGED


def test_mdd_footer_is_managed() -> None:
    assert classes("Body.\n\n> *Generated by mdd*\n")[2] is LineClass.MANAGED


def test_code_span_straddling_a_soft_break_masks_both_halves() -> None:
    lines = ok("run `a very\nlong command` now\n").lines
    assert lines[0].masks
    assert lines[1].masks
    assert lines[0].text[lines[0].masks[0].start :] == "`a very"
    assert lines[1].text[: lines[1].masks[0].end] == "long command`"


def test_link_straddling_a_soft_break_is_still_collected() -> None:
    lines = ok("see [the\ndocs](a/b.md) now\n").lines
    assert [ref.target for line in lines for ref in line.links] == ["a/b.md"]


def test_crlf_is_detected() -> None:
    result = ok("a\r\nb\r\n")
    assert result.newline == "\r\n"
    assert result.final_newline


def test_missing_final_newline_is_recorded() -> None:
    assert not ok("a").final_newline
