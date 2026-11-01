"""Tests for the write gate, which must judge a rewrite without the line classifier."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mdd.prose import gate
from mdd.prose.gate import PASSED, Verdict, compare, verify

NBSP = "\xa0"


def refused(before: str, after: str) -> Verdict:
    verdict = compare(before, after)
    assert not verdict.passed
    return verdict


def test_the_gate_does_not_import_the_classifier() -> None:
    """The gate certifies the classifier's output, so it must not share its bugs."""
    source = Path(gate.__file__).read_text(encoding="utf-8")
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert not [name for name in imported if name.startswith("mdd.prose")]


def test_identical_text_passes() -> None:
    assert verify("# Title\n\nSome prose.\n", "# Title\n\nSome prose.\n") == PASSED


# --- text and whitespace ---------------------------------------------------


def test_rewrapped_prose_passes() -> None:
    assert compare("One two three.\nFour five.\n", "One two\nthree. Four five.\n").passed


def test_collapsed_spaces_pass() -> None:
    assert compare("One  two\tthree.\n", "One two three.\n").passed


def test_changed_words_are_refused() -> None:
    verdict = refused("One two three.\n", "One two four.\n")
    assert verdict.line == 1
    assert verdict.reason == "the text changed by more than whitespace"


def test_a_deleted_space_before_punctuation_is_refused() -> None:
    """`OSC 9 ; 4` and `OSC 9; 4` render differently."""
    verdict = refused("Send OSC 9 ; 4 to it.\n", "Send OSC 9; 4 to it.\n")
    assert verdict.reason == "the text changed by more than whitespace"


def test_a_deleted_space_next_to_a_code_span_is_refused() -> None:
    """Whitespace is collapsed per text run, never stripped at a run's edge."""
    _ = refused("Run `ls` now.\n", "Run`ls` now.\n")


def test_a_preserved_no_break_space_passes() -> None:
    before = f"Ten{NBSP}km  away.\n"
    assert compare(before, f"Ten{NBSP}km\naway.\n").passed


def test_a_collapsed_no_break_space_is_refused() -> None:
    _ = refused(f"Ten{NBSP} km away.\n", "Ten km away.\n")


def test_the_reason_never_quotes_content() -> None:
    verdict = refused("A secret codename.\n", "A different codename.\n")
    assert "secret" not in verdict.reason
    assert "different" not in verdict.reason


# --- literal blocks --------------------------------------------------------


def test_prose_next_to_a_fence_may_be_rewrapped() -> None:
    before = "Intro text here.\n\n```py\nx  =  1\n```\n"
    after = "Intro\ntext here.\n\n```py\nx  =  1\n```\n"
    assert compare(before, after).passed


def test_a_change_inside_a_fence_is_refused() -> None:
    verdict = refused("Intro.\n\n```py\nx  =  1\n```\n", "Intro.\n\n```py\nx = 1\n```\n")
    assert verdict.line == 3
    assert verdict.reason == "the content of a fenced code block changed"


def test_a_changed_fence_info_string_is_refused() -> None:
    verdict = refused("```py\nx\n```\n", "```python\nx\n```\n")
    assert verdict.reason == "the info string of a fenced code block changed"


def test_a_change_inside_indented_code_is_refused() -> None:
    verdict = refused("Intro.\n\n    a\n      \n    b\n", "Intro.\n\n    a\n\n    b\n")
    assert verdict.reason == "the content of an indented code block changed"


def test_a_change_inside_an_html_block_is_refused() -> None:
    verdict = refused("<div>\na  b\n</div>\n", "<div>\na b\n</div>\n")
    assert verdict.reason == "the content of an HTML block changed"


def test_unchanged_front_matter_passes() -> None:
    before = "---\ntitle:  T\n---\n\nSome prose\nhere.\n"
    assert compare(before, "---\ntitle:  T\n---\n\nSome prose here.\n").passed


def test_changed_front_matter_is_refused() -> None:
    verdict = refused("---\ntitle:  T\n---\n\nBody.\n", "---\ntitle: T\n---\n\nBody.\n")
    assert verdict.line == 1
    assert verdict.reason == "the content of a front matter changed"


def test_a_changed_math_block_is_refused() -> None:
    verdict = refused("$$\na  +  b\n$$\n", "$$\na + b\n$$\n")
    assert verdict.reason == "the content of a math block changed"


def test_a_change_inside_an_unreferenced_footnote_is_refused() -> None:
    verdict = refused("[^1]: ``` a. B\n    c\n", "[^1]: ``` a.\n      B c\n")
    assert verdict.reason == "the info string of a fenced code block changed"


def test_a_change_inside_a_referenced_footnote_is_refused() -> None:
    before = "See[^n].\n\n[^n]: A note\n    <div>\n"
    refused(before, "See[^n].\n\n[^n]: A note <div>\n")


# --- block structure -------------------------------------------------------


def test_a_rewrapped_list_item_passes() -> None:
    before = "- one two\n  three\n- four\n"
    assert compare(before, "- one\n  two three\n- four\n").passed


def test_a_list_turning_loose_is_refused() -> None:
    verdict = refused("- one\n- two\n", "- one\n\n- two\n")
    assert verdict.reason == "a tight list became loose"


def test_a_list_turning_tight_is_refused() -> None:
    verdict = refused("- one\n\n- two\n", "- one\n- two\n")
    assert verdict.reason == "a loose list became tight"


def test_a_line_that_becomes_a_setext_underline_is_refused() -> None:
    verdict = refused("Some text and\n- a dash\n", "Some text and\n---\n")
    assert verdict.line == 1
    assert verdict.reason == "a paragraph became a heading"


def test_a_heading_level_change_is_refused() -> None:
    verdict = refused("# Title\n", "## Title\n")
    assert verdict.reason == "the tag of a heading changed"


def test_a_lazy_continuation_is_refused() -> None:
    """A paragraph swallowed into the block quote above it."""
    verdict = refused("> quoted\n\nafter\n", "> quoted\nafter\n")
    assert verdict.line == 3
    assert verdict.reason == "a paragraph was removed"


def test_an_added_block_is_refused() -> None:
    verdict = refused("Prose.\n", "Prose.\n\n```\nnot code\n```\n")
    assert verdict.line == 1
    assert verdict.reason == "a fenced code block was added"


def test_an_added_block_after_an_empty_document_is_refused() -> None:
    verdict = refused("", "# Title\n")
    assert verdict.line == 1
    assert verdict.reason == "a heading was added"


def test_a_table_next_to_rewrapped_prose_passes() -> None:
    table = "| a  | b |\n|----|---|\n| 1  | 2 |\n"
    before = f"Some prose\nhere.\n\n{table}"
    assert compare(before, f"Some prose here.\n\n{table}").passed


def test_a_broken_table_is_refused() -> None:
    before = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    verdict = refused(before, "| a | b |\n|---|--- x|\n| 1 | 2 |\n")
    assert verdict.reason == "a table became a paragraph"


def test_a_changed_table_alignment_is_refused() -> None:
    before = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    verdict = refused(before, "| a | b |\n|:--|---|\n| 1 | 2 |\n")
    assert verdict.reason == "the attributes of a table header cell changed"


# --- inline literals -------------------------------------------------------


def test_a_code_span_split_across_lines_passes() -> None:
    """CommonMark turns the line ending inside a code span into a space."""
    assert compare("Run `a b` now.\n", "Run `a\nb` now.\n").passed


def test_a_code_span_with_changed_internal_spaces_is_refused() -> None:
    verdict = refused("Run `a  b` now.\n", "Run `a b` now.\n")
    assert verdict.reason == "the content of a code span changed"


def test_changed_inline_math_is_refused() -> None:
    verdict = refused("So $a  b$ holds.\n", "So $a b$ holds.\n")
    assert verdict.reason == "the content of an inline math changed"


def test_dollar_amounts_are_text() -> None:
    assert compare("It costs $5 and $6 today.\n", "It costs $5\nand $6 today.\n").passed


def test_rewrapped_text_inside_an_inline_pre_element_is_refused() -> None:
    verdict = refused("Intro <pre>\nThe\nthe.\n</pre> end.\n", "Intro <pre> The the. </pre> end.\n")
    assert verdict.reason == "the text inside a whitespace-preserving HTML element changed"


def test_collapsed_spaces_inside_an_inline_code_element_are_refused() -> None:
    refused("A <CODE>x  y</CODE> b.\n", "A <CODE>x y</CODE> b.\n")


PRE_ACROSS_PARAGRAPHS = "Output: <pre>\n\nfirst  column  second\nnext row\n\n</pre>\n"
XMP_BLOCK_ACROSS_BLANKS = "<xmp>\n\nfirst  column  second\nnext row\n\n</xmp>\n"


def test_collapsed_spaces_in_a_pre_element_opened_in_an_earlier_paragraph_are_refused() -> None:
    after = "Output: <pre>\n\nfirst column second\nnext row\n\n</pre>\n"
    verdict = refused(PRE_ACROSS_PARAGRAPHS, after)
    assert verdict.reason == "the text inside a whitespace-preserving HTML element changed"
    assert verdict.line == 3


def test_rewrapped_text_in_a_pre_element_opened_in_an_earlier_paragraph_is_refused() -> None:
    after = "Output: <pre>\n\nfirst  column  second next row\n\n</pre>\n"
    refused(PRE_ACROSS_PARAGRAPHS, after)


def test_collapsed_spaces_in_an_xmp_element_opened_by_an_html_block_are_refused() -> None:
    after = "<xmp>\n\nfirst column second\nnext row\n\n</xmp>\n"
    refused(XMP_BLOCK_ACROSS_BLANKS, after)


def test_rewrapped_text_after_a_pre_element_closed_by_an_html_block_passes() -> None:
    before = "<pre>\na\n</pre>\n\nSome\ntext.\n"
    assert verify(before, "<pre>\na\n</pre>\n\nSome text.\n") == PASSED


def test_a_closing_tag_inside_an_html_comment_does_not_end_the_element() -> None:
    before = "<div><pre>\n<!-- </pre> -->\n\nfirst  column\n\n</pre></div>\n"
    refused(before, "<div><pre>\n<!-- </pre> -->\n\nfirst column\n\n</pre></div>\n")


def test_rewrapped_text_after_an_inline_pre_element_passes() -> None:
    before = "Intro <pre>x</pre> and then\nsome more text.\n"
    assert verify(before, "Intro <pre>x</pre> and then some more text.\n") == PASSED


def test_changed_inline_html_is_refused() -> None:
    verdict = refused('A <span  class="x">b</span>.\n', 'A <span class="x">b</span>.\n')
    assert verdict.reason == "the content of an inline HTML changed"


def test_inline_html_across_lines_keeps_the_line_count() -> None:
    before = 'A <span\nclass="x">b</span> c d.\n'
    verdict = refused(before, 'A <span\nclass="x">b</span> c e.\n')
    assert verdict.line == 2


def test_a_rewrapped_link_text_passes() -> None:
    assert compare("See [the long\ntitle](a.md).\n", "See [the long title](a.md).\n").passed


def test_a_changed_link_target_is_refused() -> None:
    verdict = refused("See [x](a.md).\n", "See [x](b.md).\n")
    assert verdict.reason == "the attributes of a link changed"


def test_a_changed_image_title_is_refused() -> None:
    verdict = refused('![alt](a.png "t  1")\n', '![alt](a.png "t 1")\n')
    assert verdict.reason == "the attributes of an image changed"


def test_rewrapped_image_alt_text_passes() -> None:
    before = "Look: ![a long\nalt text](a.png) here.\n"
    assert compare(before, "Look:\n![a long alt\ntext](a.png) here.\n").passed


def test_changed_image_alt_text_is_refused() -> None:
    verdict = refused("![one](a.png)\n", "![two](a.png)\n")
    assert verdict.reason == "the text changed by more than whitespace"


def test_an_autolink_that_stops_being_one_is_refused() -> None:
    """The bare URL is still linkified, but by a different rule."""
    verdict = refused("See <https://example.com> now.\n", "See https://example.com now.\n")
    assert verdict.reason == "the marker of a link changed"


def test_a_rewrapped_footnote_passes() -> None:
    before = "Text[^1].\n\n[^1]: A note that\n    wraps.\n"
    assert compare(before, "Text[^1].\n\n[^1]: A note\n    that wraps.\n").passed


def test_a_changed_footnote_label_is_refused() -> None:
    verdict = refused("Text[^a].\n\n[^a]: Note.\n", "Text[^b].\n\n[^b]: Note.\n")
    assert verdict.reason == "the meta of a footnote ref changed"


def test_a_changed_inline_footnote_is_refused() -> None:
    """An inline footnote's text lives outside the token stream, but it is still text."""
    verdict = refused("Text^[a b] c.\n", "Text^[a c] c.\n")
    assert verdict.reason == "the text changed by more than whitespace"


def test_a_rewrapped_inline_footnote_passes() -> None:
    assert verify("Text^[a long\nnote here] c.\n", "Text^[a long note\nhere] c.\n") == PASSED


def test_an_inline_footnote_spanning_lines_keeps_the_line_count() -> None:
    """The text after the footnote starts on the line its body ends on."""
    verdict = refused("A^[b\nc] d\ne.\n", "A^[b\nc] d\nf.\n")
    assert verdict.line == 2


# --- whitespace-preserving HTML the gate must not lose track of -------------
#
# Each pair is a whitespace-only rewrite a writer produced, or could produce,
# of text a browser renders inside a whitespace-preserving element.

LITERAL_HTML_REWRITES = [
    pytest.param(
        "Run this first sentence here.^[Keep this <pre>first sentence. Second\n"
        "sentence</pre> here.] And more.\n",
        "Run this first sentence here.^[Keep this <pre>first sentence. Second "
        "sentence</pre> here.] And more.\n",
        id="pre-inside-an-inline-footnote",
    ),
    pytest.param(
        "Body text[^1] here.\n\n[^1]: First note sentence here. Second note sentence\n"
        "    is here.\n\nLast paragraph has an open <pre>tag\n",
        "Body text[^1] here.\n\n[^1]: First note sentence here.\n"
        "      Second note sentence is here.\n\nLast paragraph has an open <pre>tag\n",
        id="footnote-rendered-after-a-pre-left-open",
    ),
    pytest.param(
        "Text <pre>a\n\n[^1]: </pre> note.\n\nfirst  column\n",
        "Text <pre>a\n\n[^1]: </pre> note.\n\nfirst column\n",
        id="footnote-closing-tag-does-not-close-the-body-pre",
    ),
    pytest.param(
        "Run this first sentence here. <script>var x = 1 // comment here\nalert(x)</script>\n",
        "Run this first sentence here. <script>var x = 1 // comment here alert(x)</script>\n",
        id="script",
    ),
    pytest.param(
        'Run <script>var s = "a  b";</script> now.\n',
        'Run <script>var s = "a b";</script> now.\n',
        id="script-spaces",
    ),
    pytest.param(
        "Some <style>p {\n  color: red }</style> text.\n",
        "Some <style>p { color: red }</style> text.\n",
        id="style",
    ),
    pytest.param(
        "Run this first sentence here. <plaintext>Keep this text on two lines\n"
        "exactly as written.\n",
        "Run this first sentence here. <plaintext>Keep this text on two lines "
        "exactly as written.\n",
        id="plaintext",
    ),
    pytest.param(
        "Run this first sentence here. <plaintext>a</plaintext>\n\nKeep  this.\n",
        "Run this first sentence here. <plaintext>a</plaintext>\n\nKeep this.\n",
        id="plaintext-never-closes",
    ),
    pytest.param(
        "Text <pre>a <script>x</pre></script>\n\nfirst  column\n",
        "Text <pre>a <script>x</pre></script>\n\nfirst column\n",
        id="closing-tag-inside-a-script-is-text",
    ),
    pytest.param(
        "<script><!--<script>\n</script>\n\nSome  text.\n",
        "<script><!--<script>\n</script>\n\nSome text.\n",
        id="script-the-first-end-tag-does-not-end",
    ),
    pytest.param(
        "Run this first sentence here. <pre/>Keep this text on two lines\nexactly as written.\n",
        "Run this first sentence here. <pre/>Keep this text on two lines exactly as written.\n",
        id="self-closing-slash",
    ),
    pytest.param(
        "Text <pre title=x/>keep  these  spaces aligned\n",
        "Text <pre title=x/>keep these spaces aligned\n",
        id="self-closing-slash-after-an-attribute",
    ),
    pytest.param(
        "Text <pre>a</code>keep  these  spaces aligned\n",
        "Text <pre>a</code>keep these spaces aligned\n",
        id="close-tag-of-another-element",
    ),
    pytest.param(
        'Run this first sentence here. <pre>a <span title="</pre>">Keep this text on\n'
        "two lines as written.</span>\n",
        'Run this first sentence here. <pre>a <span title="</pre>">Keep this text on '
        "two lines as written.</span>\n",
        id="close-tag-inside-an-attribute-value",
    ),
    pytest.param(
        '<div title="<!--"><pre>\n\nKeep this long first sentence here. Keep this second one'
        " too\nexactly as written.\n",
        '<div title="<!--"><pre>\n\nKeep this long first sentence here.\n'
        "Keep this second one too exactly as written.\n",
        id="comment-opener-inside-an-attribute-value",
    ),
    pytest.param(
        "<div><!-- a --!> <pre> -->\n\nfirst  column\n",
        "<div><!-- a --!> <pre> -->\n\nfirst column\n",
        id="comment-a-browser-ends-at-dash-dash-bang",
    ),
    pytest.param(
        "<div><!-- a ---> <pre> -->\n\nfirst  column\n",
        "<div><!-- a ---> <pre> -->\n\nfirst column\n",
        id="comment-a-browser-ends-at-three-dashes",
    ),
    pytest.param(
        "<div><!-- <pre>\n\nfirst  column\n",
        "<div><!-- <pre>\n\nfirst column\n",
        id="unclosed-comment",
    ),
    pytest.param(
        "<div title='a><pre>\n\nfirst  column\n",
        "<div title='a><pre>\n\nfirst column\n",
        id="unbalanced-quote",
    ),
    pytest.param(
        "Run this first sentence here. Cost $x <pre>$ keeps this text\non two lines as written.\n",
        "Run this first sentence here.\nCost $x <pre>$ keeps this text on two lines as written.\n",
        id="pre-inside-dollar-math",
    ),
    pytest.param(
        "Text <pre>a $x <!--$ </pre> -->\n\nfirst  column\n",
        "Text <pre>a $x <!--$ </pre> -->\n\nfirst column\n",
        id="comment-opener-inside-dollar-math",
    ),
    pytest.param(
        "Text <pre>a <?x </pre> ?>one\ntwo\n",
        "Text <pre>a <?x </pre> ?>one two\n",
        id="close-tag-inside-a-processing-instruction",
    ),
    pytest.param(
        "Text <pre>a <![CDATA[</pre>]]>one\ntwo\n",
        "Text <pre>a <![CDATA[</pre>]]>one two\n",
        id="close-tag-inside-cdata",
    ),
    pytest.param(
        "<div><?x> <pre> ?>\n\nfirst  column\n",
        "<div><?x> <pre> ?>\n\nfirst column\n",
        id="processing-instruction-a-browser-ends-early",
    ),
]


@pytest.mark.parametrize(("before", "after"), LITERAL_HTML_REWRITES)
def test_a_whitespace_change_in_whitespace_preserving_html_is_refused(
    before: str, after: str
) -> None:
    refused(before, after)


def test_prose_after_a_pre_html_block_still_reflows() -> None:
    before = '<pre class="x">\na  b\n</pre>\n\nOne\ntwo.\n\nThree\nfour.\n'
    assert verify(before, '<pre class="x">\na  b\n</pre>\n\nOne two.\n\nThree four.\n') == PASSED


def test_prose_after_a_script_html_block_still_reflows() -> None:
    before = "<script>\nif (a<b) { x(); }\n</script>\n\nSome\ntext.\n"
    assert verify(before, "<script>\nif (a<b) { x(); }\n</script>\n\nSome text.\n") == PASSED


def test_prose_after_a_closed_inline_script_still_reflows() -> None:
    before = "Run <script>x()</script> and then\nsome more.\n"
    assert verify(before, "Run <script>x()</script> and then some more.\n") == PASSED


def test_math_with_angle_brackets_reflows_without_whitespace_preserving_html() -> None:
    before = "If $a<b$ and $c>d$ then\nthis holds.\n"
    assert verify(before, "If $a<b$ and $c>d$ then this holds.\n") == PASSED


def test_any_whitespace_preserving_tag_freezes_the_footnotes() -> None:
    """Footnotes render after the body, whose final state the gate does not trust."""
    before = "Intro <pre>x</pre> text[^1].\n\n[^1]: A note\n    that wraps.\n"
    refused(before, "Intro <pre>x</pre> text[^1].\n\n[^1]: A note that\n    wraps.\n")


# --- hard breaks -----------------------------------------------------------


def test_a_kept_hard_break_passes() -> None:
    assert compare("One  two  \nthree four\n", "One two  \nthree\nfour\n").passed


def test_a_lost_hard_break_is_refused() -> None:
    verdict = refused("One   \ntwo\n", "One\ntwo\n")
    assert verdict.line == 1
    assert verdict.reason == "a hard line break was lost"


def test_a_lost_backslash_hard_break_is_refused() -> None:
    verdict = refused("One\\\ntwo three\n", "One two\nthree\n")
    assert verdict.reason == "a hard line break was lost"


def test_an_added_hard_break_is_refused() -> None:
    verdict = refused("One\ntwo\n", "One  \ntwo\n")
    assert verdict.reason == "a hard line break was added"


# --- failure modes ---------------------------------------------------------


def test_a_parser_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(_text: str) -> list[object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(gate, "_items", explode)
    verdict = compare("a\n", "a\n")
    assert verdict == Verdict(passed=False, reason="the document could not be parsed")


def test_verify_refuses_when_the_model_renders_differently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered = iter(["one", "two"])

    def differently(_text: str) -> str:
        return next(rendered)

    monkeypatch.setattr(gate, "canonical", differently)
    verdict = verify("a\n", "a\n")
    assert not verdict.passed
    assert verdict.reason == "the document renders differently in mdd's model"


def test_verify_refuses_when_the_model_cannot_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    def unparseable(_text: str) -> None:
        return None

    monkeypatch.setattr(gate, "canonical", unparseable)
    verdict = verify("a\n", "a\n")
    assert verdict.reason == "the document could not be parsed into mdd's model"


def test_verify_reports_the_token_difference_first() -> None:
    verdict = verify("# heading\n", "heading\n")
    assert verdict.reason == "a heading became a paragraph"


def test_canonical_renders_parseable_input() -> None:
    assert gate.canonical("ok\n") is not None


def test_canonical_returns_none_when_the_model_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(_text: str) -> object:
        raise ValueError("boom")

    monkeypatch.setattr(gate, "parse_markdown", explode)
    assert gate.canonical("ok\n") is None


# --- nesting limit ---------------------------------------------------------

#: Ten nested list items: markdown-it stops parsing the content of the tenth.
TEN_DEEP = "".join(f"{'  ' * depth}- level {depth}\n" for depth in range(10))


def test_a_change_past_the_parser_nesting_limit_is_refused() -> None:
    inner = " " * 20
    before = f"{TEN_DEEP}{inner}foo   \n{inner}[x]: /u\n"
    after = f"{TEN_DEEP}{inner}foo\n{inner}[x]: /u\n"
    verdict = refused(before, after)
    assert verdict.reason == "the document nests too deeply to compare"
    assert verdict.line == 10


def test_a_lost_hard_break_in_a_quote_past_the_nesting_limit_is_refused() -> None:
    deep = "> " * 20
    refused(f"{deep}a   \n{deep}b\n", f"{deep}a\n{deep}b\n")


def test_a_deep_but_comparable_document_passes() -> None:
    before = "> " * 15 + "a\n" + "> " * 15 + "b\n"
    assert verify(before, "> " * 15 + "a b\n") == PASSED


def test_a_model_refusal_names_the_first_changed_line(monkeypatch: pytest.MonkeyPatch) -> None:
    rendered = iter(["one", "two"])

    def differently(_text: str) -> str:
        return next(rendered)

    def passes(_before: str, _after: str) -> Verdict:
        return PASSED

    monkeypatch.setattr(gate, "canonical", differently)
    monkeypatch.setattr(gate, "compare", passes)
    verdict = verify("a\nb\nc\n", "a\nb\nC\n")
    assert verdict == Verdict(
        passed=False, line=3, reason="the document renders differently in mdd's model"
    )


@pytest.mark.parametrize(
    ("before", "after", "line"),
    [("a\nb\n", "a\nc\n", 2), ("a\n", "a\nb\n", 2), ("a\nb\n", "a\n", 2), ("a\n", "a\n", 0)],
)
def test_first_changed_line(before: str, after: str, line: int) -> None:
    assert gate._first_changed_line(before, after) == line  # pyright: ignore[reportPrivateUsage]
