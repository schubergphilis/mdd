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
from mdd.prose.inline import scan
from mdd.prose.reflow.apply import equivalent, reflow_text, structurally_stable

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


def test_a_quoted_fence_does_not_close_an_outer_fence() -> None:
    """A `>`-prefixed ``` closed the fence, making the rest of the block prose."""
    text = "Intro.\n\n```markdown\n> A quote:\n>\n> ```\n> code  in  quote\n> ```\n```\n"
    assert set(classes(text)[2:9]) == {"fenced-code"}


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
    assert lint_write(target) == 0
    assert read_file(target).splitlines()[2] == "Also two, and two. and two: here."


def test_a_fixed_file_is_clean_on_a_second_run(tmp_path: Path) -> None:
    """Overlap resolution has to pick the edit that leaves nothing to find."""
    target = tmp_path / "a.md"
    write_file(target, "Intro.\n\nAlso two  , and trailing.   \n")
    assert lint_write(target) == 0
    assert cli_main(["prose", "lint", str(target)]) == 0


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
    assert not structurally_stable(before, after)
    assert not equivalent(before, after)


def test_gate_rejects_output_that_no_longer_classifies() -> None:
    assert not equivalent("Some prose.\n", "```\nunclosed\n")


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
