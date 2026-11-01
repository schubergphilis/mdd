"""Property tests: the line classifier and both writers against a markdown-it oracle.

The documents come from :mod:`tests.prose.strategies`. Every property drives the
real code path a user hits: the writers run through :func:`mdd.prose.runner.run`
with ``write=True`` against a file on disk, so whatever gate the runner applies
before writing is part of what is under test.

The oracle in :mod:`tests.prose.oracle` is deliberately independent of
:mod:`mdd.prose`. Two implementations that agree are evidence; one
implementation checked against itself is not.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from hypothesis import event, given

from mdd.prose import runner
from mdd.prose.classify import Classified, LineClass, classify
from mdd.prose.config import ProseConfig
from tests.prose.oracle import (
    PARSER,
    assert_same_document,
    paragraph_line_indices,
    verbatim_line_indices,
)
from tests.prose.strategies import Document, documents

# --- driving the writers ----------------------------------------------------


@dataclass(frozen=True)
class WriteOutcome:
    """What a writer left on disk, and what the runner reported about it."""

    text: str
    refused: bool
    written: int


def run_writer(check: str, text: str) -> WriteOutcome:
    """Run ``mdd prose <check> --write`` over *text* in a file, and read it back.

    A temporary directory per call, not ``tmp_path``: a function-scoped fixture
    is shared across every example Hypothesis generates.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "doc.md"
        _ = path.write_bytes(text.encode("utf-8"))
        result = runner.run([path], ProseConfig(), runner.RunOptions(checks=(check,), write=True))
        after = path.read_bytes().decode("utf-8")
    refused = any(finding.rule == "parse-error" for finding in result.findings)
    return WriteOutcome(text=after, refused=refused, written=result.written)


def misplaced_prose(text: str) -> list[str]:
    """Lines the classifier calls prose that markdown-it does not put in a paragraph.

    Empty when the classifier refuses *text*: a refused file is never written,
    so there is nothing for a disagreement to damage.
    """
    classified = classify(text)
    if not isinstance(classified, Classified):
        return []
    tokens = PARSER.parse(text)
    literal = verbatim_line_indices(tokens)
    paragraph = paragraph_line_indices(tokens)
    out: list[str] = []
    for line in classified.lines:
        if line.cls is not LineClass.PROSE:
            continue
        index = line.number - 1
        if index in literal:
            out.append(f"line {line.number} is literal: {line.text!r}")
        elif index not in paragraph:
            out.append(f"line {line.number} is not paragraph text: {line.text!r}")
    return out


def label(document: Document) -> None:
    """Record what went into *document*, for ``--hypothesis-show-statistics``."""
    for kind in sorted(set(document.kinds)):
        event(f"block: {kind}")


# --- properties -------------------------------------------------------------


@given(documents())
def test_prose_lines_are_paragraph_lines(document: Document) -> None:
    """Every line the classifier calls prose is paragraph text according to markdown-it."""
    label(document)
    assert misplaced_prose(document.text) == []


@given(documents())
def test_reflow_write_preserves_the_document(document: Document) -> None:
    """Whatever ``reflow --write`` leaves on disk means what the original meant."""
    label(document)
    outcome = run_writer("reflow", document.text)
    event(f"reflow wrote: {bool(outcome.written)}")
    assert_same_document(document.text, outcome.text)


@given(documents())
def test_lint_write_preserves_the_document(document: Document) -> None:
    """Whatever ``lint --write`` leaves on disk means what the original meant."""
    label(document)
    outcome = run_writer("lint", document.text)
    event(f"lint wrote: {bool(outcome.written)}")
    assert_same_document(document.text, outcome.text)


@given(documents())
def test_reflow_write_is_idempotent(document: Document) -> None:
    """Reflowing the reflowed file changes nothing."""
    once = run_writer("reflow", document.text)
    twice = run_writer("reflow", once.text)
    assert twice.text == once.text


@given(documents())
def test_lint_write_is_idempotent(document: Document) -> None:
    """Linting the linted file changes nothing."""
    once = run_writer("lint", document.text)
    twice = run_writer("lint", once.text)
    assert twice.text == once.text


@given(documents(allow_unclosed=True))
def test_refused_file_is_never_written(document: Document) -> None:
    """A file the classifier refuses comes back from either writer byte for byte."""
    label(document)
    for check in ("reflow", "lint"):
        outcome = run_writer(check, document.text)
        event(f"{check} refused: {outcome.refused}")
        if outcome.refused:
            assert outcome.written == 0
            assert outcome.text == document.text


# --- counterexamples ----------------------------------------------------------
#
# Minimal inputs the properties above found, shrunk by hand, kept so that a
# fixed defect stays fixed under the derandomized ci profile too.

CLASSIFIER_COUNTEREXAMPLES = [
    pytest.param("<pre>\na\n\nb\n</pre>\n", id="html-block-survives-blank-line"),
    pytest.param("Intro.\n<div>\nb\n</div>\n", id="html-block-interrupts-paragraph"),
    pytest.param("# h\n    code\n", id="indented-code-after-heading"),
    pytest.param("a\n===\n    code\n", id="indented-code-after-setext-heading"),
    pytest.param("# h\n<span>\nb\n", id="html-block-after-heading"),
    pytest.param("[x]:\n/u\n", id="multi-line-link-definition"),
    pytest.param("[x]: /u\n'title'\n", id="link-definition-title-on-next-line"),
    pytest.param("[x]: /u 'a\nb'\n", id="link-definition-title-over-two-lines"),
    pytest.param("[x]: /u\n[y]:\n/v\n", id="link-definition-after-link-definition"),
    pytest.param("[x]:\n      /u\n  'title'\n", id="link-definition-destination-indented-as-code"),
    pytest.param("- [x]: /u\n", id="link-definition-in-list-item"),
    pytest.param("- [x]:\n  /u\n  'title'\n", id="multi-line-link-definition-in-list-item"),
    pytest.param("- ```\n```\na  b\n```\nc\n```\n", id="fence-ended-by-its-list-item"),
    pytest.param(
        "1. a\n   ```\n   > b\n   ```\n   c  d\n   ```\n",
        id="quote-shaped-line-in-a-list-item-fence",
    ),
    pytest.param("> ```\n> a\nb\n> ```\nc  d\n", id="fence-ended-by-its-block-quote"),
    pytest.param("a\n>     code\n", id="indented-code-opening-a-block-quote"),
    pytest.param("- ::: callout-tip\nb\n:::\n", id="fenced-div-in-list-item-drops-a-line"),
    pytest.param("::: x\n:::\n2. a\n\n\tb\n", id="list-item-after-unknown-div-continues-it"),
    pytest.param("a\n   -\n\n        code\n", id="bare-marker-under-a-paragraph-opens-no-list"),
    pytest.param("- a\nb\n-\n\n\tc\n", id="empty-item-closes-at-a-blank-line"),
    pytest.param("1. a\n   b\n2. c\n\t***\n", id="rule-in-a-sibling-list-item"),
    pytest.param("1. a\n2. ```\n```\n\nb\n", id="fence-in-a-sibling-list-item"),
    pytest.param("- a\n\n\t>***\n", id="rule-in-a-block-quote-in-a-list-item"),
    pytest.param(
        "1.   a\n\n     > ```\n     > b  c\n     > ```\n",
        id="fence-in-a-block-quote-in-a-list-item",
    ),
    pytest.param("| a |\n| --- |\n", id="single-column-table"),
    pytest.param("| a |\n|---|\nfoo\n", id="table-row-without-a-pipe"),
    pytest.param("| a |\n|---|\n[x]: /u\nfoo\n", id="link-definition-as-table-row"),
    pytest.param("| a |\n|---|\n$$ x $$\nfoo\n", id="math-as-table-row"),
    pytest.param("| a | b |\n|---|---|\n| c | d |\n===\n", id="equals-row-under-a-table"),
    pytest.param("- ***\n", id="thematic-break-after-list-marker"),
    pytest.param("- # h\n", id="heading-after-list-marker"),
    pytest.param("1. $$ x $$\n", id="math-after-list-marker"),
    pytest.param("-     code  x\n", id="indented-code-after-list-marker"),
    pytest.param("-   \tcode  x\n", id="indented-code-after-list-marker-and-tab"),
    pytest.param("- <div>\n", id="html-block-after-list-marker"),
    pytest.param("[^1]: ``` a\n    c\n", id="fence-after-footnote-label"),
    pytest.param("10.\nfoo\n", id="empty-list-item"),
    pytest.param("[^1]:\nfoo\n", id="empty-footnote-label"),
    pytest.param("- a\n  -\n", id="setext-heading-in-list-item"),
    pytest.param("para\n- <span>\n", id="bare-tag-html-block-opens-list-item"),
    pytest.param("- > # h\n", id="heading-in-quote-in-list-item"),
    pytest.param("1.   ```\n     a  b\n     ```\nc\n", id="fence-after-wide-list-marker"),
    pytest.param("-    a\n\n     $$\n     x\n     $$\n", id="math-block-in-list-item"),
    pytest.param("$$ a\nb\nc $$\n", id="math-block-content-on-opener"),
    pytest.param("$$ a\nb $$ (1)\nc\n", id="math-block-closed-by-a-label"),
    pytest.param("-    a\n\n     # h\n", id="heading-at-list-content-column"),
    pytest.param("1.   a\n\n     <div>\n     x\n", id="html-block-at-list-content-column"),
    pytest.param("[^1]:# A sentence. B.\n", id="footnote-without-space"),
    pytest.param("---\n---\n\nThe\n:::.\n=", id="unknown-div-name-in-setext-heading"),
    pytest.param("The\n:::\n=\n", id="unmatched-div-closer-in-setext-heading"),
]


@pytest.mark.parametrize("text", CLASSIFIER_COUNTEREXAMPLES)
def test_classifier_counterexample(text: str) -> None:
    assert misplaced_prose(text) == []


WRITER_DAMAGE = [
    pytest.param(
        "reflow",
        "[^1]:# A sentence. B.\n",
        id="reflow-splits-footnote-heading",
    ),
    pytest.param(
        "reflow",
        "$$ a\nb\nc $$\n",
        id="reflow-joins-math-lines",
    ),
    pytest.param(
        "reflow",
        "[^1]: :80 it\n    configuration ;block\n    <div>\n",
        id="reflow-joins-html-into-footnote",
    ),
    pytest.param(
        "reflow",
        "[^1]: ``` a. B\n    c\n",
        id="reflow-splits-footnote-fence-info",
    ),
    pytest.param(
        "reflow",
        "- 1. $$\n    a\n    b\n    $$\n",
        id="reflow-joins-math-in-nested-list",
    ),
    pytest.param(
        "reflow",
        "- <pre>\nOne.\nTwo.\n</pre>\n",
        id="reflow-rewrites-raw-pre",
    ),
    pytest.param(
        "lint",
        "a   \nb\n",
        id="lint-deletes-hard-break",
    ),
    pytest.param(
        "lint",
        "OSC 9 ; 4\n",
        id="lint-space-before-punctuation",
    ),
    pytest.param(
        "lint",
        "<textarea>\na  b\n\nc  d\n</textarea>\n",
        id="lint-rewrites-html-block",
    ),
    pytest.param(
        "lint",
        "# h\n    a  b\n",
        id="lint-rewrites-indented-code",
    ),
    pytest.param(
        "lint",
        "Intro.\n<div>\nb  c\n</div>\n",
        id="lint-rewrites-interrupting-html",
    ),
    pytest.param(
        "lint",
        "-     code  x\n",
        id="lint-rewrites-list-item-code",
    ),
    pytest.param(
        "reflow",
        "1. | the |\n| --- |\n\n\xa0The\nthe.\n2. \xa0The\nthe.\n3. <pre>\nThe\nthe.\n</pre>",
        id="reflow-joins-lines-inside-inline-pre",
    ),
    pytest.param(
        "lint",
        "---\n---\n\n\xa0The\nthe.\n\n\xa0The\nthe.\n\n1. ***\n"
        "2. <!-- mdd-prose-ignore: trailing-whitespace -->\n\xa0The\nthe.\n3. The\n\tthe.\n\n"
        "\t::: callout-tip\n\n\t\xa0The\n\tthe.\n \n\t:::",
        id="lint-trims-blank-line-inside-list-item-code",
    ),
]

REFLOW_UNSTABLE = [
    pytest.param(
        ">\xa0The\nthe.\n>\n[^1]: The\n>    No.\n    5\n    the.\n    The\n    the\n"
        "    the\n    the\n    the\n>    the.",
        id="reflow-unstable-footnote-with-lazy-quote-lines",
    ),
    pytest.param("> a\nb\n> c\n", id="reflow-unstable-quote-after-lazy-line"),
]


@pytest.mark.parametrize("text", REFLOW_UNSTABLE)
def test_reflow_counterexample_is_idempotent(text: str) -> None:
    once = run_writer("reflow", text)
    assert run_writer("reflow", once.text).text == once.text


@pytest.mark.parametrize(("check", "text"), WRITER_DAMAGE)
def test_writer_counterexample(check: str, text: str) -> None:
    assert_same_document(text, run_writer(check, text).text)
