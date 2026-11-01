"""The write gate: proof that a rewrite did not change what a document means.

Both writers, ``reflow --write`` and ``lint --write``, produce their output
from the prose line classifier. The classifier approximates CommonMark block
parsing by hand, so it must not also be what certifies that its own output is
safe. This module therefore never imports it. It parses the text before and
after a rewrite with markdown-it, configured as mdd's own flavour plus the
front matter, footnote and dollar-math plugins so those constructs are seen as
the literal blocks they are, and requires the two token streams to agree:

- the same block tokens in the same order: type, nesting, tag, markup, info,
  attributes and ``hidden``, which is what tells a tight list from a loose one;
- byte-identical content in every block token that carries any, which covers
  fences, indented code, HTML blocks, math blocks and front matter;
- inline content that matches once runs of Markdown whitespace (space, tab,
  line ending, soft break) are collapsed to one space. No-break and other
  Unicode spaces are not Markdown whitespace and must match exactly, as must
  code spans, inline math, inline HTML, link and image attributes, and every
  hard line break.

On top of that, the text must render identically through mdd's own Markdown
model. The two comparisons are blind to different things: the model drops
distinctions the token stream keeps, and the token stream knows nothing of the
normalisation the model applies.
"""

from __future__ import annotations

from mdd.markdown.ir import parse_markdown, render_markdown
from mdd.prose.gate.stream import TooDeep, items
from mdd.prose.gate.verdict import PASSED, Verdict, content, structure
from mdd.utils.logging import get_logger

__all__ = ["PASSED", "Verdict", "canonical", "compare", "verify"]

log = get_logger(__name__)


def compare(before: str, after: str) -> Verdict:
    """Compare the markdown-it token streams of *before* and *after*.

    Shape is compared before content. A structural change, such as a
    paragraph absorbed into a block quote as a lazy continuation, also
    changes the text, and the structural reason is the one worth reading.
    """
    try:
        left = items(before)
        right = items(after)
    except TooDeep as deep:
        return Verdict(
            passed=False, line=deep.line, reason="the document nests too deeply to compare"
        )
    except Exception:  # any parse failure means "cannot prove equivalence"
        log.debug("write gate: markdown did not parse", exc_info=True)
        return Verdict(passed=False, reason="the document could not be parsed")
    verdict = structure(left, right)
    return verdict if not verdict.passed else content(left, right)


def canonical(text: str) -> str | None:
    """Return *text* parsed, normalised and re-rendered, or ``None`` if it will not parse."""
    try:
        return render_markdown(parse_markdown(text))
    except Exception:  # any parse failure means "cannot prove equivalence"
        log.debug("write gate: markdown did not parse into the IR", exc_info=True)
        return None


def _first_changed_line(before: str, after: str) -> int:
    """Return the 1-based number of the first line of *before* the rewrite changed.

    The model comparison cannot say where two documents diverge, only that
    they do, so it names the first line the rewrite touched instead. ``0``
    when no line differs.
    """
    old, new = before.splitlines(), after.splitlines()
    for number, (old_line, new_line) in enumerate(zip(old, new, strict=False), start=1):
        if old_line != new_line:
            return number
    return min(len(old), len(new)) + 1 if len(old) != len(new) else 0


def verify(before: str, after: str) -> Verdict:
    """Decide whether *after* may replace *before* on disk.

    The token comparison runs first because it can say where the documents
    diverge. The model comparison can only say that they do.
    """
    verdict = compare(before, after)
    if not verdict.passed:
        return verdict
    left = canonical(before)
    right = canonical(after)
    if left is None or right is None:
        return Verdict(passed=False, reason="the document could not be parsed into mdd's model")
    if left != right:
        return Verdict(
            passed=False,
            line=_first_changed_line(before, after),
            reason="the document renders differently in mdd's model",
        )
    return PASSED
