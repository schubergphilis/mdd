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
    assert classes("| a | b |\n|---|---|\n| 1 | 2 |\n\nafter\n") == [
        LineClass.TABLE,
        LineClass.TABLE,
        LineClass.TABLE,
        LineClass.BLANK,
        LineClass.PROSE,
    ]


def test_a_line_directly_under_a_table_is_a_row() -> None:
    # GFM ends a table at a blank line or another block, not at a line
    # without a pipe.
    assert classes("| a |\n|---|\nafter\n") == [LineClass.TABLE] * 3


def test_a_block_start_ends_a_table() -> None:
    table = [LineClass.TABLE] * 2
    assert classes("| a |\n|---|\n# h\n") == [*table, LineClass.HEADING]
    assert classes("| a |\n|---|\n> q\n") == [*table, LineClass.PROSE]
    assert classes("| a |\n|---|\n- i\n") == [*table, LineClass.PROSE]


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


def blocks(text: str) -> list[int]:
    return [line.block for line in ok(text).lines]


def test_deeper_indented_list_continuation_joins_the_item() -> None:
    assert blocks("- item one\n      continued here\n") == [1, 1]


def test_lazy_list_continuation_joins_the_item() -> None:
    assert blocks("- item one\ncontinued lazily\n") == [1, 1]


def test_shallower_list_continuation_joins_the_item() -> None:
    assert blocks("1. item one\n continued\n") == [1, 1]


def test_indented_block_quote_continuation_joins_the_paragraph() -> None:
    assert blocks("> quoted\n>    more\n") == [1, 1]


def test_lazy_block_quote_continuation_joins_the_paragraph() -> None:
    assert blocks("> quoted\nlazy line\n") == [1, 1]


def test_lazy_continuation_of_a_nested_quote_joins_the_paragraph() -> None:
    assert blocks("> > deep\n> shallower\n") == [1, 1]


def test_a_deeper_block_quote_starts_a_new_block() -> None:
    assert blocks("> a\n> > b\n") == [1, 2]


def test_a_list_marker_starts_a_new_block() -> None:
    assert blocks("- a\n- b\n  c\n") == [1, 2, 2]


def test_code_span_straddling_an_indented_continuation_is_masked() -> None:
    lines = ok("- run `a very\n      long command` now\n").lines
    assert lines[0].text[lines[0].masks[0].start :] == "`a very"
    assert lines[1].text[: lines[1].masks[0].end] == "      long command`"


def test_a_bare_list_marker_is_not_prose() -> None:
    # An empty item, or one whose content starts on the next line. Joining it
    # into a paragraph turns a list item into text.
    marker, prose = LineClass.LIST_MARKER, LineClass.PROSE
    assert classes("1.\nfoo\n") == [marker, prose]
    assert classes("> -\n> foo\n") == [marker, prose]
    assert classes("- a\n*\n") == [prose, marker]


def test_a_dash_under_a_paragraph_is_a_setext_underline() -> None:
    assert classes("foo\n-\n") == [LineClass.HEADING, LineClass.HEADING]


def test_a_setext_underline_inside_a_list_item_makes_a_heading() -> None:
    assert classes("- a\n  ---\n") == [LineClass.HEADING, LineClass.HEADING]
    assert classes("- a\n---\n") == [LineClass.PROSE, LineClass.THEMATIC_BREAK]


def test_list_item_content_is_classified_by_the_block_it_opens() -> None:
    assert classes("- # h\n") == [LineClass.HEADING]
    assert classes("- ***\n") == [LineClass.THEMATIC_BREAK]
    assert classes("1. [x]: /u\n") == [LineClass.LINK_DEF]
    assert classes("-     code\n") == [LineClass.INDENTED_CODE]
    assert classes("- ```\n  a  b\n  ```\n") == [LineClass.FENCED_CODE] * 3
    assert classes("[^1]:# h\n") == [LineClass.HEADING]


def test_list_content_column_counts_a_tab_after_the_marker_as_columns() -> None:
    # `-\t` puts the content at column 4, so six spaces is a paragraph inside
    # the item, not code. Counting the tab as one character set the floor at 6.
    text = "-\titem\n\n      para\n"
    assert classes(text)[2] is LineClass.PROSE


def test_list_content_column_counts_a_tab_before_the_marker_as_columns() -> None:
    text = "- outer\n\n\t- inner\n\n        para\n"
    assert classes(text)[4] is LineClass.PROSE


def test_five_spaces_after_a_marker_put_the_content_one_column_in() -> None:
    # Five or more spaces after the marker make the content column the marker
    # plus one, so a six-space line after a blank is code inside the item.
    text = "-      x\n\n      code  here\n"
    assert classes(text)[2] is LineClass.INDENTED_CODE


def test_a_tab_run_after_the_marker_wider_than_four_columns() -> None:
    text = "-\t\tx\n\n      code  here\n"
    assert classes(text)[2] is LineClass.INDENTED_CODE
