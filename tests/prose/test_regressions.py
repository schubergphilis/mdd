"""Regression tests, one per defect found in review of the initial implementation.

Each test here corresponds to a reproduced bug. They are collected in one file
rather than scattered so the class of failure stays visible: almost every one is
"a rewriter changed bytes it had no business touching", and the tests that guard
against that are worth reading together.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from mdd.cli import main as cli_main
from mdd.prose.classify import Classified, ClassifyError, LineClass, classify
from mdd.prose.config import ReflowConfig
from mdd.prose.gate import verify
from mdd.prose.inline import scan
from mdd.prose.reflow.apply import reflow_text

if TYPE_CHECKING:
    from pathlib import Path

NBSP = "\xa0"


def ok(text: str) -> Classified:
    result = classify(text)
    assert isinstance(result, Classified), result
    return result


def classes(text: str) -> list[str]:
    return [line.cls.value for line in ok(text).lines]


def reflow(text: str) -> str:
    return reflow_text(ok(text), ReflowConfig()).text


def write_file(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        _ = handle.write(text)


def read_file(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def lint_write(path: Path) -> int:
    return cli_main(["prose", "lint", "--write", str(path)])


# --- byte fidelity -------------------------------------------------------


def test_crlf_survives_a_lint_write(tmp_path: Path) -> None:
    """`read_text()` translated CRLF to LF, so every write rewrote the whole file."""
    target = tmp_path / "a.md"
    write_file(target, "Intro.\r\n\r\nTrailing here   \r\n")
    assert lint_write(target) == 0
    after = read_file(target)
    assert "\n" not in after.replace("\r\n", ""), "a bare LF was introduced"
    assert after == "Intro.\r\n\r\nTrailing here\r\n"


def test_mixed_line_endings_fail_closed() -> None:
    """Splitting on one terminator left the other embedded and lost bytes."""
    result = classify("One.\nTwo.\r\nThree.\n")
    assert isinstance(result, ClassifyError)
    assert "line endings" in result.reason


def test_no_break_space_is_content_not_indentation() -> None:
    """`.strip()` deleted a leading NBSP, turning a paragraph into a real fence."""
    source = f"A paragraph long enough to be realistic here.\n\n{NBSP}```\nnot code\n{NBSP}```\n"
    out = reflow(source)
    assert NBSP in out
    assert isinstance(classify(out), Classified)


def test_a_leading_tab_is_preserved_and_idempotent() -> None:
    """The indent was re-emitted as `" " * n`, converting a tab to a space."""
    source = "\t> \tSome quoted prose. And more of it.\n"
    once = reflow(source)
    assert once.startswith("\t")
    assert reflow(once) == once


def test_tab_indent_counts_as_four_columns() -> None:
    """Counting characters made a tab-indented code block look like prose."""
    assert classes("Paragraph.\n\n\tif x:  # code\n")[2] == "indented-code"


# --- the classifier ------------------------------------------------------


def test_every_line_of_an_indented_code_block_is_code() -> None:
    """Only the first line was code; the rest were handed to the fixers as prose."""
    text = "Example:\n\n    def f(x):\n        return  x + 1\n    f(2)\n\nDone.\n"
    assert classes(text)[2:5] == ["indented-code"] * 3


def test_blank_line_inside_indented_code_is_not_a_blank_run(tmp_path: Path) -> None:
    """`blank-run` deleted a blank line that was code content."""
    target = tmp_path / "a.md"
    source = "Intro.\n\n    code_a = 1\n\n\n    code_b = 2\n\nEnd.\n"
    write_file(target, source)
    assert lint_write(target) == 0
    assert read_file(target) == source


def test_a_whitespace_line_in_code_after_a_closed_list_is_not_trimmed(tmp_path: Path) -> None:
    """The list had ended, so the indented block was code, not list content.

    An HTML block cannot be lazily continued, so `a` closes the list, and `2. b`
    continues the paragraph `a` because an item numbered 2 cannot interrupt
    one. Taking `2.` for a list item put the code floor out of reach, and
    `trailing-whitespace` trimmed a line of the code block.
    """
    target = tmp_path / "a.md"
    source = "1. <!-- c -->\na\n2. b\n\n    c\n \n    d\n"
    write_file(target, source)
    assert lint_write(target) == 0
    assert read_file(target) == source


def test_a_quoted_fence_does_not_close_an_outer_fence() -> None:
    """A `>`-prefixed ``` closed the fence, making the rest of the block prose."""
    text = "Intro.\n\n```markdown\n> A quote:\n>\n> ```\n> code  in  quote\n> ```\n```\n"
    assert set(classes(text)[2:9]) == {"fenced-code"}


def test_an_open_block_quote_continues_on_a_marker_at_any_indent() -> None:
    """markdown-it continues an open block quote on a `>` however far it is indented.

    A tab before the `>` made the line read as paragraph text, so the code
    fence it opens was handed to the fixers.
    """
    assert classes("> a\n\t> ```\n\t> x  y\n\t> ```\n") == [
        "prose",
        "fenced-code",
        "fenced-code",
        "fenced-code",
    ]
    # A blank line closes the quote: the same line is then indented code.
    assert classes("> a\n\n\t> b  c\n") == ["prose", "blank", "indented-code"]


def test_html_block_cannot_interrupt_a_paragraph() -> None:
    """A mid-paragraph autolink line swallowed the rest of the paragraph."""
    assert classes("Some prose continues\n<https://example.com/x>.\nMore prose.\n")[1] == "prose"


def test_setext_rule_after_a_list_is_not_a_heading() -> None:
    """`- a\\n- b\\n---` turned the list into a heading and invented anchors."""
    assert LineClass.HEADING.value not in classes("- see below\n- see below\n---\n\nTail.\n")


def test_fenced_div_marker_is_not_prose() -> None:
    """`:::callout-tip` was joined into the paragraph below it, destroying the callout."""
    assert classes(":::callout-tip\nA tip. Two sentences.\n:::\n") == [
        "div-marker",
        "prose",
        "div-marker",
    ]


def test_colon_line_the_div_renderer_ignores_is_paragraph_text() -> None:
    """The renderer opens a div only on a name it knows, and closes only an open one.

    Calling `:::.` or a stray `:::` a div marker split the paragraph, so the
    `=` below it read as prose rather than the underline of a setext heading.
    """
    assert classes("The\n:::.\n=\n") == ["heading", "heading", "heading"]
    assert classes("The\n:::\n=\n") == ["heading", "heading", "heading"]
    assert classes("::: unknown-name\nA.\n:::\n") == ["prose", "prose", "prose"]


def test_closer_of_an_open_div_is_a_marker() -> None:
    """Only a run of exactly the opener's colons closes the div it opened."""
    assert classes("::::layout\n:::layout-section\nA.\n:::\n::::\n") == [
        "div-marker",
        "div-marker",
        "prose",
        "div-marker",
        "div-marker",
    ]
    assert classes(":::callout-tip\nA.\n::::\n:::\n") == [
        "div-marker",
        "prose",
        "prose",
        "div-marker",
    ]
    # A lazy line may close a div opened in a block quote. Such a line stays a
    # marker, and the div stays open for any later run of the same colons.
    assert classes("> :::callout-tip\n> A.\n:::\nB.\n:::\n") == [
        "div-marker",
        "prose",
        "div-marker",
        "prose",
        "div-marker",
    ]


def test_indented_code_containing_a_comment_opener_does_not_fail_closed() -> None:
    """`<!--` inside indented code raised a false "comment never closes" error."""
    assert isinstance(classify("Para.\n\n    <!-- not a comment\n    still code\n"), Classified)


# --- inline masking ------------------------------------------------------


def test_unclosed_backtick_run_does_not_swallow_the_next_code_span() -> None:
    """Restarting inside the run let it close against the next span's opener."""
    text = "Wrap it in ``` fences and pass `--write  --json` to apply."
    assert "`--write  --json`" in [text[s.start : s.end] for s in scan(text).masks]


def test_whitespace_inside_a_straddling_code_span_survives(tmp_path: Path) -> None:
    """Masks stop at the rstripped content, so a trailing run inside a span was deleted."""
    target = tmp_path / "a.md"
    source = "Use `foo   \nbar` command here.\n"
    write_file(target, source)
    assert lint_write(target) == 0
    assert read_file(target) == source


def test_whitespace_inside_every_masked_construct_survives_a_write(tmp_path: Path) -> None:
    """The spec asks for *every* masked construct, not just an inline-code span."""
    constructs = [
        "`code  span`",
        "[link  text](a/b.md)",
        "![alt  text](i.png)",
        "<https://example.test/a__b>",
        "<span  class='x'>",
        "a[^note  ref]",
        "$math  here$",
        # No `escape` case: a backslash escape covers exactly two characters and
        # only ever escapes punctuation, so it has no interior whitespace to
        # protect. `\` + space is not an escape at all, and collapsing the run
        # after it is a correct fix rather than a mask violation.
    ]
    for index, construct in enumerate(constructs):
        target = tmp_path / f"m{index}.md"
        source = f"Prose around {construct} and more.\n"
        write_file(target, source)
        assert lint_write(target) == 0, construct
        assert read_file(target) == source, construct


# --- the edit layer ------------------------------------------------------


def test_overlapping_edits_do_not_delete_the_punctuation(tmp_path: Path) -> None:
    """Two rules matched one run; the second's stale end offset ate the mark."""
    target = tmp_path / "a.md"
    write_file(target, "Intro.\n\nAlso two  , and two  . and two  : here.\n")
    assert lint_write(target) == 1  # the unfixable space before each mark remains
    assert read_file(target).splitlines()[2] == "Also two , and two . and two : here."


def test_a_fixed_file_is_stable_on_a_second_run(tmp_path: Path) -> None:
    """Overlap resolution has to pick the edit that leaves nothing fixable."""
    target = tmp_path / "a.md"
    write_file(target, "Intro.\n\nAlso two  , and trailing.   \n")
    _ = lint_write(target)
    once = read_file(target)
    assert once.splitlines()[2] == "Also two , and trailing."
    _ = lint_write(target)
    assert read_file(target) == once


def test_space_before_a_path_or_ellipsis_is_left_alone(tmp_path: Path) -> None:
    """The alnum-only guard still ate the space in `directory ./configs`."""
    target = tmp_path / "a.md"
    source = "Intro.\n\nIt lives in ./configs and up .. one level, and `a`, ...) too.\n"
    write_file(target, source)
    assert lint_write(target) == 0
    assert read_file(target) == source


def test_a_suppressed_rule_is_not_fixed(tmp_path: Path) -> None:
    """The finding was silenced but the fix was still applied."""
    target = tmp_path / "a.md"
    source = "Intro.\n\n<!-- mdd-prose-ignore: trailing-whitespace -->\nTrailing here   \n"
    write_file(target, source)
    assert lint_write(target) == 0
    assert read_file(target) == source


def test_a_file_wide_suppression_is_not_fixed(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    source = "<!-- mdd-prose-ignore-file: multiple-spaces -->\n\nAlso  two  spaces.\n"
    write_file(target, source)
    assert lint_write(target) == 0
    assert read_file(target) == source


# --- the equivalence gate ------------------------------------------------


def test_gate_rejects_a_reflow_that_manufactures_a_block() -> None:
    """The render comparison was blind to a generated line becoming a fence."""
    before = "Some prose.\n"
    after = "Some prose.\n\n```\nnot code\n```\n"
    assert not verify(before, after).passed


def test_gate_rejects_output_that_no_longer_classifies() -> None:
    assert not verify("Some prose.\n", "```\nunclosed\n").passed


# --- anchors -------------------------------------------------------------


def test_slug_keeps_a_trailing_hyphen_from_removed_punctuation(tmp_path: Path) -> None:
    """`.strip()` produced `ship-it`, rejecting the working link `#ship-it-`."""
    target = tmp_path / "a.md"
    write_file(target, "# Ship it \U0001f680\n\nsee [x](#ship-it-) here\n")
    assert cli_main(["prose", "anchors", str(target)]) == 0


def test_root_absolute_targets_are_not_resolved_from_the_filesystem_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`path.parent / "/etc/passwd"` discarded the left side and read the host's file."""
    target = tmp_path / "a.md"
    write_file(target, "# T\n\nsee [a](/etc/passwd#root) here\n")
    assert cli_main(["prose", "anchors", str(target)]) == 0
    assert "passwd" not in capsys.readouterr().out


# --- the write path ------------------------------------------------------


def test_a_symlink_is_not_replaced_with_a_regular_file(tmp_path: Path) -> None:
    real = tmp_path / "real.md"
    write_file(real, "Intro.\n\nTrailing here   \n")
    link = tmp_path / "link.md"
    link.symlink_to(real)
    assert lint_write(link) == 1
    assert link.is_symlink()


def test_reflow_write_refuses_a_mirrored_file(tmp_path: Path) -> None:
    """The spec requires both writers to be tested against the shared refusals."""
    target = tmp_path / "a.md"
    source = (
        "---\nconfluence:\n  page_id: '1'\n---\n\n"
        "One sentence that runs on for a while, with a clause. And a second one.\n"
    )
    write_file(target, source)
    config = tmp_path / "prose.yaml"
    _ = config.write_text("prose:\n  checks:\n    reflow: error\n", encoding="utf-8")
    assert cli_main(["prose", "reflow", "--write", "--config", str(config), str(target)]) == 1
    assert read_file(target) == source


def test_reflow_write_with_json_is_a_usage_error(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    write_file(target, "One. Two.\n")
    with pytest.raises(SystemExit) as exc:
        _ = cli_main(["prose", "reflow", "--write", "--json", str(target)])
    assert exc.value.code == 2


def test_reflow_does_not_write_an_ignored_file(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    target = tmp_path / "docs" / "a.md"
    source = "One sentence that runs on for a while, with a clause. And a second one.\n"
    write_file(target, source)
    _ = (tmp_path / "docs" / ".mddignore").write_text("a.md\n", encoding="utf-8")
    assert cli_main(["prose", "reflow", "--write", str(tmp_path / "docs")]) == 0
    assert read_file(target) == source


# --- third review round: the write guards ---------------------------------

MIRROR_SOURCE = "---\nconfluence:\n  page_id: 123\n---\n\nfoo   \n"


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(MIRROR_SOURCE.replace("\n", "\r\n"), id="crlf"),
        pytest.param(MIRROR_SOURCE.replace("\n", "\r"), id="cr-only"),
        pytest.param("\ufeff" + MIRROR_SOURCE, id="bom"),
        pytest.param("---\n: : :\n---\n\nfoo   \n", id="unparseable"),
    ],
)
def test_lint_write_refuses_a_mirror_whatever_its_line_endings(
    tmp_path: Path, source: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The guard read CRLF, CR-only and BOM front matter as no front matter at all."""
    target = tmp_path / "a.md"
    write_file(target, source)
    assert lint_write(target) == 1
    assert read_file(target) == source
    assert "mirrored-file" in capsys.readouterr().out


LONG_PARAGRAPH = (
    "This is the first sentence of the paragraph. "
    "This is the second sentence which is long enough to matter.\n"
)


@pytest.mark.parametrize(
    "directive",
    [
        pytest.param("<!-- mdd-prose-ignore-file: reflow -->\n\n", id="file-wide"),
        pytest.param("<!-- mdd-prose-ignore-file -->\n\n", id="bare-file-wide"),
        pytest.param("<!-- mdd-prose-ignore: reflow -->\n", id="line"),
        pytest.param("<!-- mdd-prose-ignore -->\n", id="bare-line"),
    ],
)
def test_reflow_write_leaves_a_suppressed_paragraph_alone(tmp_path: Path, directive: str) -> None:
    """The finding was suppressed but reflow --write still rewrote the paragraph."""
    target = tmp_path / "a.md"
    source = directive + LONG_PARAGRAPH
    write_file(target, source)
    assert cli_main(["prose", "reflow", "--write", str(target)]) == 0
    assert read_file(target) == source


def test_reflow_write_still_fixes_the_paragraphs_that_are_not_suppressed(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    source = "<!-- mdd-prose-ignore: reflow -->\n" + LONG_PARAGRAPH + "\n" + LONG_PARAGRAPH
    write_file(target, source)
    assert cli_main(["prose", "reflow", "--write", str(target)]) == 0
    first, _, second = read_file(target).partition("\n\n")
    assert first + "\n" == "<!-- mdd-prose-ignore: reflow -->\n" + LONG_PARAGRAPH
    assert second.count("\n") == 2


def test_a_held_paragraph_reports_its_other_lines_as_not_fixable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The suppression keeps --write off the paragraph, so nothing in it is fixable."""
    target = tmp_path / "a.md"
    source = (
        "<!-- mdd-prose-ignore: reflow -->\nShort first sentence here.\n"
        "This is the second line of the paragraph. It has two sentences in it.\n"
    )
    write_file(target, source)
    assert cli_main(["prose", "reflow", "--json", str(target)]) == 1
    out = capsys.readouterr().out
    assert '"line": 3' in out
    assert '"fixable": false' in out
    assert cli_main(["prose", "reflow", "--write", str(target)]) == 1
    assert read_file(target) == source


def test_lint_write_leaves_a_line_under_a_bare_suppression_alone(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    source = "Intro.\n\n<!-- mdd-prose-ignore -->\nTwo  spaces   \n"
    write_file(target, source)
    assert lint_write(target) == 0
    assert read_file(target) == source


def test_a_directive_quoted_in_a_code_span_does_not_stop_a_fix(tmp_path: Path) -> None:
    """Showing the syntax in backticks switched every check off for the whole file."""
    target = tmp_path / "a.md"
    write_file(target, "Write `<!-- mdd-prose-ignore-file -->` to opt out.\n\nfoo   \n")
    assert lint_write(target) == 0
    assert read_file(target) == "Write `<!-- mdd-prose-ignore-file -->` to opt out.\n\nfoo\n"


# --- second review round: block state that outlived its block ------------


@pytest.mark.parametrize(
    "closer",
    ["# Heading", "```\nfenced\n```", "---", "***"],
    ids=["heading", "fence", "setext-rule", "thematic-break"],
)
def test_a_list_stops_raising_the_indented_code_floor(closer: str) -> None:
    """The list's content column outlived the list, so real code read as prose.

    Only a paragraph cleared it: a heading, a fence or a thematic break returned
    before the tracker ran. The floor stayed at four-plus-the-marker, a genuine
    four-space code block fell under it, and `lint --write` rewrote its interior.
    """
    source = f"- item\n\n{closer}\n\n    def f():\n        return  1\n\ntail\n"
    assert "indented-code" in classes(source)


def test_a_marker_after_a_wide_gap_is_code_not_a_nested_item() -> None:
    """Five columns after a marker start indented code, so a marker there opens nothing.

    `-       1. a` was read as an item nested in an item. That put the
    content column at the `1.` item's, so the code line below read as prose.
    """
    assert classes("-       1. a\n\t    b\n") == ["indented-code", "indented-code"]


def test_a_four_space_block_after_a_list_keeps_its_double_spaces(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    source = "- item\n\n# H\n\n    def f():\n        return  1\n\ntail\n"
    write_file(target, source)
    assert lint_write(target) == 0
    assert read_file(target) == source


def test_a_backtick_fence_may_not_carry_a_backtick_in_its_info_string() -> None:
    """CommonMark 4.7. Opening a block here made a real code block read as prose."""
    source = "```x`y\n\nprose  here\n\n```\ncode  here\n```\n"
    assert classes(source)[0] == "prose"


def test_a_tilde_fence_may_carry_a_backtick_in_its_info_string() -> None:
    source = "~~~x`y\ncode\n~~~\n"
    assert classes(source) == ["fenced-code", "fenced-code", "fenced-code"]


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (f"```\ncode\n```{NBSP}\nafter\n", "fenced code block never closes"),
        (f"---\ntitle: t\n---{NBSP}\nbody\n", "frontmatter block never closes"),
        (f"$$\nx\n$${NBSP}\nafter\n", "math block never closes"),
    ],
    ids=["fence", "frontmatter", "math"],
)
def test_a_no_break_space_does_not_close_a_block(source: str, reason: str) -> None:
    """`str.strip()` ate U+00A0, so a line that is not a closer closed the block.

    The block ended early and its remaining content — real code, real maths —
    became prose the fixers would rewrite. Failing closed is the safe direction.
    """
    result = classify(source)
    assert isinstance(result, ClassifyError)
    assert result.reason == reason


def test_a_no_break_space_line_is_not_a_blank_line(tmp_path: Path) -> None:
    """It was classified BLANK, so `blank-run` deleted a line holding content."""
    target = tmp_path / "a.md"
    source = f"Intro.\n\n{NBSP}\n\nTail.\n"
    write_file(target, source)
    _ = lint_write(target)
    assert NBSP in read_file(target)


def _timed(source: str) -> float:
    start = time.perf_counter()
    _ = classify(source)
    return time.perf_counter() - start


def test_reclaiming_code_blanks_is_linear() -> None:
    """The reclaim pass re-scanned the whole file from every blank line.

    Quadratic: a file of ordinary prose spent longer in this pass than in the
    rest of the classifier put together. Quadrupling the input should roughly
    quadruple the time; the old pass took nine times as long. The bound is loose
    because a shared runner is noisy, and best-of-three damps the rest.
    """

    def best(count: int) -> float:
        source = "para\n\n" * count
        return min(_timed(source) for _ in range(3))

    assert best(8_000) * 6.5 > best(32_000)


def test_a_blank_between_two_indented_code_lines_is_still_reclaimed() -> None:
    source = "para\n\n    code\n\n    more code\n\ntail\n"
    assert classes(source) == [
        "prose",
        "blank",
        "indented-code",
        "indented-code",
        "indented-code",
        "blank",
        "prose",
    ]


# --- third review round: containers, CommonMark divergences ---------------


@pytest.mark.parametrize(
    ("source", "prefix", "cont_prefix"),
    [
        ("- >   - a  b\n", "- >   - ", "  >     "),
        ("[^n]: -   a  b\n", "[^n]: -   ", "          "),
        ("- 1. a  b\n", "- 1. ", "     "),
    ],
)
def test_nested_container_markers_are_prefix(source: str, prefix: str, cont_prefix: str) -> None:
    line = ok(source).lines[0]
    assert (line.cls, line.prefix, line.cont_prefix) == (LineClass.PROSE, prefix, cont_prefix)


def test_lint_leaves_the_gap_after_nested_markers_alone(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    write_file(path, "- >   - a  b\n")
    _ = lint_write(path)
    assert read_file(path) == "- >   - a b\n"


def test_a_lazy_line_is_not_a_setext_underline() -> None:
    assert classes("> a\n===\n") == ["prose", "prose"]


def test_a_setext_underline_finds_its_paragraph_across_a_lazy_line() -> None:
    source = "> 1. a\nb\n> c\n=\n"
    assert classes(source) == ["prose"] * 4
    assert {line.block for line in ok(source).lines} == {1}


def test_a_line_less_indented_than_a_list_item_table_ends_the_list() -> None:
    source = "1. a\n2. b | c\n   --- | ---\nd | e\n3. f\n\n    code  x\n"
    assert classes(source) == [
        "prose",
        "table",
        "table",
        "prose",
        "prose",
        "blank",
        "indented-code",
    ]


def test_an_indented_row_of_a_list_item_table_is_a_row() -> None:
    source = "- b | c\n  --- | ---\n  d | e\n\n      code  x\n"
    assert classes(source) == ["table", "table", "table", "blank", "indented-code"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # A `>` indented four columns continues the quote in markdown-it and is
        # code, or paragraph text, in CommonMark.
        ("> Quote\n>\n    > two  spaces here\n", ["prose", "block-quote", "divergent"]),
        ("> alpha\n    > beta gamma\n", ["divergent", "divergent"]),
        ("- a\n\n  > b\n  > c  d\n", ["prose", "blank", "prose", "prose"]),
        ("10. a\n\n    > b\n    > c  d\n", ["prose", "blank", "prose", "prose"]),
        # A lazy line indented four columns is code in markdown-it and
        # paragraph text in CommonMark, so the line above it may end in a
        # hard break or not.
        ("> > Note the following   \n    - item text\n", ["divergent", "divergent"]),
        ("> > first line   \n    second line\n", ["divergent", "divergent"]),
        ("> a\n> b\n   c\n", ["prose", "prose", "prose"]),
    ],
)
def test_lines_commonmark_renderers_disagree_on_are_not_prose(
    source: str, expected: list[str]
) -> None:
    assert classes(source) == expected


@pytest.mark.parametrize(
    ("check", "source"),
    [
        ("lint", "> Quote\n>\n    > two  spaces here\n"),
        ("reflow", "> alpha\n    > beta gamma\n"),
        ("lint", "> > first line   \n    second line\n"),
        ("lint", "> > Note the following   \n    - item text\n"),
    ],
)
def test_writers_leave_divergent_lines_alone(tmp_path: Path, check: str, source: str) -> None:
    path = tmp_path / "doc.md"
    write_file(path, source)
    _ = cli_main(["prose", check, "--write", str(path)])
    assert read_file(path) == source


def test_a_marker_that_cannot_interrupt_a_paragraph_is_its_text() -> None:
    lines = ok("Para\n10. more\n5.\n").lines
    assert [line.cls.value for line in lines] == ["prose"] * 3
    assert [line.prefix for line in lines] == ["", "", ""]
    assert {line.block for line in lines} == {1}


BOM_FRONT_MATTER = "\ufeff---\ntitle: x\ntags:\n- a  b\n---\n\nSome  text.\n"


def test_front_matter_after_a_byte_order_mark_is_front_matter() -> None:
    assert classes(BOM_FRONT_MATTER) == ["frontmatter"] * 5 + ["blank", "prose"]


def test_lint_leaves_front_matter_after_a_byte_order_mark_alone(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    write_file(path, BOM_FRONT_MATTER)
    _ = lint_write(path)
    assert read_file(path).startswith("\ufeff---\ntitle: x\ntags:\n- a  b\n---\n")


@pytest.mark.parametrize(
    "source",
    [
        "- [a]: /u\n\n\n  b\n",
        "- a\n\n\n  b\n",
        "1. a\n\n\n\n   - b\n",
    ],
)
def test_blank_lines_in_a_list_item_before_an_indented_line_are_kept(
    tmp_path: Path, source: str
) -> None:
    path = tmp_path / "doc.md"
    write_file(path, source)
    _ = lint_write(path)
    assert read_file(path) == source


def test_blank_lines_after_a_list_before_an_unindented_line_are_collapsed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "doc.md"
    write_file(path, "- a\n\n\nb\n")
    _ = lint_write(path)
    assert read_file(path) == "- a\n\nb\n"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('[a^b]: /url  "Big  title"\n', ["link-target"]),
        ('[a^b]:\n/url\n"title  one\n  two  three"\n', ["link-target"] * 4),
        ("[a\\]b]: /u  'x  y'\n", ["link-target"]),
        ("[a\\\\]: /u  'x  y'\n", ["link-target"]),
        ("[\\^a]: /u  'x  y'\n", ["link-target"]),
        ("[ ]: /u 'x  y'\n", ["prose"]),
        ("[a[b]: /u 'x  y'\n", ["prose"]),
        # CommonMark caps a label at 999 characters; neither renderer here does.
        ("[" + "a" * 1000 + "]: /u 'x  y'\n", ["link-target"]),
        ("[^n]: a  b\n", ["prose"]),
    ],
)
def test_link_definition_labels_follow_commonmark(source: str, expected: list[str]) -> None:
    assert classes(source) == expected
