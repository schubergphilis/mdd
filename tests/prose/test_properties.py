"""Property tests: the line classifier and both writers against a markdown-it oracle.

The documents come from :mod:`tests.prose.strategies`. Every property drives the
real code path a user hits: the writers run through :func:`mdd.prose.runner.run`
with ``write=True`` against a file on disk, so whatever gate the runner applies
before writing is part of what is under test.

The oracle below is deliberately independent of :mod:`mdd.prose`. It parses
with markdown-it-py directly, in mdd's own flavour plus the front matter,
footnote and dollar-math plugins, and never asks the production code what a
line is. Two implementations that agree are evidence; one implementation
checked against itself is not.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from hypothesis import Phase, event, given, settings
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin

from mdd.markdown.ir.flavour import build_md
from mdd.prose import runner
from mdd.prose.classify import Classified, LineClass, classify
from mdd.prose.config import ProseConfig
from tests.prose.strategies import Document, documents

if TYPE_CHECKING:
    from markdown_it import MarkdownIt
    from markdown_it.token import Token

# --- the oracle: markdown-it only, nothing from mdd.prose -------------------

#: Block tokens whose content is literal. A writer must not change one byte.
VERBATIM_TOKENS = frozenset(
    {"fence", "code_block", "html_block", "math_block", "math_block_label", "front_matter"}
)

#: Markdown's own whitespace. Not `\s`: a no-break space is content.
_MD_WHITESPACE = re.compile(r"[ \t\r\n]+")

#: Elements whose whitespace is significant in the rendered output.
_LITERAL_ELEMENT = re.compile(r"(<code[^>]*>.*?</code>|<pre[^>]*>.*?</pre>)", re.DOTALL)


def oracle_parser() -> MarkdownIt:
    """The mdd flavour, plus the syntax extensions a prose file may carry.

    The footnote plugin normally moves definitions to the end of the document
    and drops the ones nothing references, taking their source map with them.
    Keeping them where they were written means an edit inside an unreferenced
    footnote still shows up in the rendered output.
    """
    md = build_md().use(front_matter_plugin).use(footnote_plugin).use(dollarmath_plugin)
    return md.disable("footnote_tail")


_PARSER = oracle_parser()


def oracle_lines(text: str) -> list[str]:
    """Split *text* into source lines the way markdown-it numbers them."""
    return re.split(r"\r\n|\r|\n", text)


def rendered(text: str) -> str:
    """Render *text* to HTML with insignificant whitespace runs collapsed.

    A soft line break and a space render identically, which is what lets a
    reflow move one. Inside ``<code>`` and ``<pre>`` whitespace is content, so
    those elements are kept byte for byte.
    """
    html = _PARSER.render(text)
    parts = _LITERAL_ELEMENT.split(html)
    return "".join(
        part if index % 2 else _MD_WHITESPACE.sub(" ", part) for index, part in enumerate(parts)
    ).strip()


@dataclass(frozen=True)
class Verbatim:
    """One literal block: its token type, markdown-it's content, and its source lines."""

    kind: str
    content: str
    source: tuple[str, ...]


def verbatim_blocks(text: str) -> list[Verbatim]:
    """Every literal block in *text*, in document order."""
    lines = oracle_lines(text)
    out: list[Verbatim] = []
    for token in _PARSER.parse(text):
        if token.type not in VERBATIM_TOKENS or token.map is None:
            continue
        start, end = token.map
        out.append(Verbatim(token.type, token.content, tuple(lines[start:end])))
    return out


def verbatim_line_indices(tokens: list[Token]) -> set[int]:
    """Zero-based source lines that markdown-it puts inside a literal block."""
    out: set[int] = set()
    for token in tokens:
        if token.type in VERBATIM_TOKENS and token.map is not None:
            out.update(range(*token.map))
    return out


def paragraph_line_indices(tokens: list[Token]) -> set[int]:
    """Zero-based source lines that markdown-it puts inside a paragraph."""
    out: set[int] = set()
    for token in tokens:
        if token.type == "paragraph_open" and token.map is not None:
            out.update(range(*token.map))
    return out


def assert_same_document(before: str, after: str) -> None:
    """Fail unless *after* means exactly what *before* meant."""
    if before == after:
        return
    assert verbatim_blocks(after) == verbatim_blocks(before), "a literal block changed"
    assert rendered(after) == rendered(before), "the rendered document changed"


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
    tokens = _PARSER.parse(text)
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
#
# Two properties are expected to fail until the defects recorded in the
# counterexample section below are fixed. They are marked non-strict so that a
# fix which makes them pass does not break the build; drop the marker then.
# They also skip shrinking: a known failure is not worth twenty seconds of
# every test run, and the counterexamples below are already minimal.

KNOWN_FAILURE = settings(phases=(Phase.explicit, Phase.reuse, Phase.generate))


@pytest.mark.xfail(
    strict=False,
    reason="the classifier still calls several non-paragraph constructs prose; "
    "each one is pinned by a strict counterexample below",
)
@KNOWN_FAILURE
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


@pytest.mark.xfail(
    strict=False,
    reason="lint --write has no equivalence gate yet, so every classifier gap "
    "below reaches the disk; drop this marker once the gate lands",
)
@KNOWN_FAILURE
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
# Minimal inputs the properties above found, shrunk by hand. Each is a known
# defect, marked strict so the marker has to come off when the defect is fixed.


def _gap(text: str, reason: str, name: str) -> object:
    return pytest.param(text, id=name, marks=pytest.mark.xfail(strict=True, reason=reason))


CLASSIFIER_GAPS = [
    _gap(
        "<pre>\na\n\nb\n</pre>\n",
        "an HTML block of kinds 1 to 5 is ended by a blank line instead of its end tag",
        "html-block-survives-blank-line",
    ),
    _gap(
        "Intro.\n<div>\nb\n</div>\n",
        "an HTML block of kinds 1 to 6 that interrupts a paragraph is called prose",
        "html-block-interrupts-paragraph",
    ),
    _gap(
        "# h\n    code\n",
        "indented code straight after a heading is called prose",
        "indented-code-after-heading",
    ),
    _gap(
        "[x]:\n/u\n",
        "a link reference definition spread over several lines is called prose",
        "multi-line-link-definition",
    ),
    _gap(
        "- [x]: /u\n",
        "a link reference definition inside a list item is called prose",
        "link-definition-in-list-item",
    ),
    _gap(
        "| a |\n| --- |\n",
        "a single-column table is called prose",
        "single-column-table",
    ),
    _gap(
        "- ***\n",
        "a thematic break on a list marker line is called prose",
        "thematic-break-after-list-marker",
    ),
    _gap(
        "- # h\n",
        "an ATX heading on a list marker line is called prose",
        "heading-after-list-marker",
    ),
    _gap(
        "1. $$ x $$\n",
        "a math block on a list marker line is called prose",
        "math-after-list-marker",
    ),
    _gap(
        "-     code  x\n",
        "indented code opened by five spaces after a list marker is called prose",
        "indented-code-after-list-marker",
    ),
    _gap(
        "- <div>\n",
        "an HTML block on a list marker line is called prose",
        "html-block-after-list-marker",
    ),
    _gap(
        "[^1]: ``` a\n    c\n",
        "a fence on a footnote definition line is called prose",
        "fence-after-footnote-label",
    ),
    _gap(
        "10.\nfoo\n",
        "a bare list marker, an empty list item, is called prose",
        "empty-list-item",
    ),
    _gap(
        "-    a\n\n     $$\n     x\n     $$\n",
        "a math block indented to a list item's content column is called prose",
        "math-block-in-list-item",
    ),
    _gap(
        "$$ a\nb\nc $$\n",
        "a math block with content on its opening line is closed after one line",
        "math-block-content-on-opener",
    ),
    _gap(
        "[^1]:# A sentence. B.\n",
        "a footnote definition with no space after the colon is called prose",
        "footnote-without-space",
    ),
]


@pytest.mark.parametrize("text", CLASSIFIER_GAPS)
def test_classifier_counterexample(text: str) -> None:
    assert misplaced_prose(text) == []


WRITER_DAMAGE = [
    pytest.param(
        "reflow",
        "[^1]:# A sentence. B.\n",
        id="reflow-splits-footnote-heading",
        marks=pytest.mark.xfail(
            strict=True, reason="reflow moves the second sentence out of the footnote's heading"
        ),
    ),
    pytest.param(
        "reflow",
        "$$ a\nb\nc $$\n",
        id="reflow-joins-math-lines",
        marks=pytest.mark.xfail(strict=True, reason="reflow joins two lines of a math block"),
    ),
    pytest.param(
        "reflow",
        "[^1]: :80 it\n    configuration ;block\n    <div>\n",
        id="reflow-joins-html-into-footnote",
        marks=pytest.mark.xfail(
            strict=True, reason="reflow joins an HTML block into a footnote's paragraph"
        ),
    ),
    pytest.param(
        "reflow",
        "[^1]: ``` a. B\n    c\n",
        id="reflow-splits-footnote-fence-info",
        marks=pytest.mark.xfail(
            strict=True, reason="reflow moves part of a fence's info string into the code"
        ),
    ),
    pytest.param(
        "reflow",
        "- 1. $$\n    a\n    b\n    $$\n",
        id="reflow-joins-math-in-nested-list",
        marks=pytest.mark.xfail(
            strict=True, reason="reflow joins the lines of a math block inside a nested list"
        ),
    ),
    pytest.param(
        "reflow",
        "- <pre>\nOne.\nTwo.\n</pre>\n",
        id="reflow-rewrites-raw-pre",
        marks=pytest.mark.xfail(
            strict=True,
            reason="reflow rewrites text a raw <pre> opened on a list marker line keeps literal",
        ),
    ),
    pytest.param(
        "lint",
        "a   \nb\n",
        id="lint-deletes-hard-break",
        marks=pytest.mark.xfail(
            strict=True, reason="trailing-whitespace deletes a hard break of three or more spaces"
        ),
    ),
    pytest.param(
        "lint",
        "OSC 9 ; 4\n",
        id="lint-space-before-punctuation",
        marks=pytest.mark.xfail(
            strict=True, reason="space-before-punctuation changes the rendered text"
        ),
    ),
    pytest.param(
        "lint",
        "<textarea>\na  b\n\nc  d\n</textarea>\n",
        id="lint-rewrites-html-block",
        marks=pytest.mark.xfail(
            strict=True, reason="multiple-spaces rewrites an HTML block after a blank line"
        ),
    ),
    pytest.param(
        "lint",
        "# h\n    a  b\n",
        id="lint-rewrites-indented-code",
        marks=pytest.mark.xfail(
            strict=True, reason="multiple-spaces rewrites indented code that follows a heading"
        ),
    ),
    pytest.param(
        "lint",
        "Intro.\n<div>\nb  c\n</div>\n",
        id="lint-rewrites-interrupting-html",
        marks=pytest.mark.xfail(
            strict=True, reason="multiple-spaces rewrites an HTML block that interrupts a paragraph"
        ),
    ),
    pytest.param(
        "lint",
        "-     code  x\n",
        id="lint-rewrites-list-item-code",
        marks=pytest.mark.xfail(
            strict=True, reason="multiple-spaces rewrites indented code inside a list item"
        ),
    ),
]


@pytest.mark.parametrize(("check", "text"), WRITER_DAMAGE)
def test_writer_counterexample(check: str, text: str) -> None:
    assert_same_document(text, run_writer(check, text).text)
