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

import functools
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin

from mdd.markdown.ir import parse_markdown, render_markdown
from mdd.markdown.ir.flavour import build_md
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from markdown_it import MarkdownIt
    from markdown_it.token import Token

log = get_logger(__name__)

#: Runs of Markdown whitespace. Deliberately ASCII only: a no-break space is a
#: typographic choice, and collapsing it would let a writer silently drop one.
_MARKDOWN_WHITESPACE = re.compile(r"[ \t\r\n]+")

#: Human-readable names for token types, for the reason a user is shown.
_NOUNS: dict[str, str] = {
    "blockquote": "block quote",
    "bullet_list": "bulleted list",
    "code_block": "indented code block",
    "code_inline": "code span",
    "em": "emphasis",
    "fence": "fenced code block",
    "front_matter": "front matter",
    "hardbreak": "hard line break",
    "hr": "thematic break",
    "html_block": "HTML block",
    "html_inline": "inline HTML",
    "math_block": "math block",
    "math_inline": "inline math",
    "ordered_list": "numbered list",
    "s": "strikethrough",
    "strong": "strong emphasis",
    "td": "table cell",
    "th": "table header cell",
    "tr": "table row",
}


@dataclass(frozen=True)
class Verdict:
    """Whether a rewrite passed the gate and, if not, where and why it failed.

    ``line`` is 1-based and counts lines of the text *before* the rewrite; it
    is ``0`` when the difference has no single position. ``reason`` is shown
    to users, so it names the construct that changed but never quotes content.
    """

    passed: bool
    line: int = 0
    reason: str = ""


PASSED = Verdict(passed=True)


@dataclass(frozen=True)
class _Item:
    """One comparable unit of a token stream.

    ``key`` is the structural identity two items must share. ``literal`` is
    the content that must then also match: exact for literal constructs, with
    whitespace collapsed for text.
    """

    type: str
    key: tuple[object, ...]
    literal: str
    line: int


@functools.cache
def _parser() -> MarkdownIt:
    # The pandoc rules for `$`: no space just inside the delimiters and no
    # digit after the closing one, so that "costs $5 and $6" stays text.
    # Footnote definitions stay where they are written: the tail rule moves
    # them to the end and drops any that nothing references, which would hide
    # a change inside an unreferenced footnote from the comparison.
    return (
        build_md()
        .use(front_matter_plugin)
        .use(footnote_plugin)
        .use(dollarmath_plugin, allow_space=False, allow_digits=False)
        .disable("footnote_tail")
    )


def _noun(token_type: str) -> str:
    base = token_type.removesuffix("_open").removesuffix("_close")
    return _NOUNS.get(base, base.replace("_", " "))


def _attrs(token: Token) -> tuple[tuple[str, str | int | float], ...]:
    return tuple(sorted(token.attrs.items()))


def _shape(token: Token) -> tuple[object, ...]:
    """Everything about *token* except its content and its position."""
    return (
        token.type,
        token.nesting,
        token.tag,
        token.markup,
        token.info,
        _attrs(token),
        token.hidden,
        repr(sorted(token.meta.items())) if token.meta else "",
    )


def _collapse(text: str) -> str:
    return _MARKDOWN_WHITESPACE.sub(" ", text)


class _InlineFlattener:
    """Turns one inline token's children into comparable items."""

    def __init__(self, line: int) -> None:
        self.line = line
        self.items: list[_Item] = []
        self._text: list[str] = []
        self._text_line = line

    def _flush(self) -> None:
        if self._text:
            joined = _collapse("".join(self._text))
            self.items.append(_Item("text", ("text",), joined, self._text_line))
            self._text = []

    def feed(self, children: Sequence[Token]) -> None:
        for child in children:
            self._feed_one(child)

    def _feed_one(self, child: Token) -> None:
        if child.type in {"text", "softbreak"}:
            if not self._text:
                self._text_line = self.line
            if child.type == "softbreak":
                self._text.append("\n")
                self.line += 1
            else:
                self._text.append(child.content)
            return
        self._flush()
        if child.children:
            # An image's alt text arrives twice: raw as content, and parsed as
            # children. The children are compared, as text, so it may rewrap.
            self.items.append(_Item(child.type, _shape(child), "", self.line))
            self.feed(child.children)
            self._flush()
            return
        # Everything else keeps its content byte for byte. That is the point
        # for code spans, math and inline HTML, and fails closed for any plugin
        # token this module does not know about.
        self.items.append(_Item(child.type, _shape(child), child.content, self.line))
        self.line += 1 if child.type == "hardbreak" else child.content.count("\n")

    def finish(self) -> list[_Item]:
        """Flush pending text and strip the whitespace at either end."""
        self._flush()
        items = self.items
        if items and items[0].type == "text":
            first = items[0]
            items[0] = _Item("text", first.key, first.literal.lstrip(" "), first.line)
        if items and items[-1].type == "text":
            last = items[-1]
            items[-1] = _Item("text", last.key, last.literal.rstrip(" "), last.line)
        return [item for item in items if item.type != "text" or item.literal]


def _items(text: str) -> list[_Item]:
    """Flatten *text*'s token stream into comparable items."""
    items: list[_Item] = []
    line = 1
    for token in _parser().parse(text):
        if token.map is not None:
            line = token.map[0] + 1
        if token.type == "inline":
            flattener = _InlineFlattener(line)
            flattener.feed(token.children or [])
            items.extend(flattener.finish())
            continue
        items.append(_Item(token.type, _shape(token), token.content, line))
    return items


def _noun_phrase(token_type: str) -> str:
    noun = _noun(token_type)
    article = "an" if noun.startswith(("a", "e", "i", "o", "u", "HTML")) else "a"
    return f"{article} {noun}"


def _differing_field(before: _Item, after: _Item) -> str:
    names = ("type", "nesting", "tag", "marker", "info string", "attributes", "hidden", "meta")
    for name, left, right in zip(names, before.key, after.key, strict=False):
        if left != right:
            return name
    return "shape"


def _hard_breaks(items: Sequence[_Item]) -> int:
    return sum(item.type == "hardbreak" for item in items)


def _structural_reason(
    before: _Item, after: _Item, left: Sequence[_Item], right: Sequence[_Item]
) -> str:
    """Say how the shape of *after* differs from *before*.

    A lost hard break surfaces as a hard break lined up against whatever
    followed it, so the break count is consulted before blaming that token.
    """
    lost = _hard_breaks(left) - _hard_breaks(right)
    if lost > 0:
        return "a hard line break was lost"
    if lost < 0:
        return "a hard line break was added"
    if before.type != after.type:
        return f"{_noun_phrase(before.type)} became {_noun_phrase(after.type)}"
    field = _differing_field(before, after)
    if field == "hidden" and before.type == "paragraph_open":
        return "a tight list became loose" if before.key[6] else "a loose list became tight"
    return f"the {field} of {_noun_phrase(before.type)} changed"


def _structure(left: Sequence[_Item], right: Sequence[_Item]) -> Verdict:
    """The first difference in shape, ignoring content."""
    for old, new in zip(left, right, strict=False):
        if old.key != new.key:
            reason = _structural_reason(old, new, left, right)
            return Verdict(passed=False, line=old.line, reason=reason)
    if len(left) > len(right):
        missing = left[len(right)]
        reason = f"{_noun_phrase(missing.type)} was removed"
        return Verdict(passed=False, line=missing.line, reason=reason)
    if len(right) > len(left):
        extra = right[len(left)]
        line = left[-1].line if left else 1
        return Verdict(passed=False, line=line, reason=f"{_noun_phrase(extra.type)} was added")
    return PASSED


def _content(left: Sequence[_Item], right: Sequence[_Item]) -> Verdict:
    """The first difference in content, for two streams of the same shape."""
    for old, new in zip(left, right, strict=True):
        if old.literal == new.literal:
            continue
        if old.type == "text":
            reason = "the text changed by more than whitespace"
        else:
            reason = f"the content of {_noun_phrase(old.type)} changed"
        return Verdict(passed=False, line=old.line, reason=reason)
    return PASSED


def compare(before: str, after: str) -> Verdict:
    """Compare the markdown-it token streams of *before* and *after*.

    Shape is compared before content. A structural change, such as a
    paragraph absorbed into a block quote as a lazy continuation, also
    changes the text, and the structural reason is the one worth reading.
    """
    try:
        left = _items(before)
        right = _items(after)
    except Exception:  # any parse failure means "cannot prove equivalence"
        log.debug("write gate: markdown did not parse", exc_info=True)
        return Verdict(passed=False, reason="the document could not be parsed")
    verdict = _structure(left, right)
    return verdict if not verdict.passed else _content(left, right)


def canonical(text: str) -> str | None:
    """Return *text* parsed, normalised and re-rendered, or ``None`` if it will not parse."""
    try:
        return render_markdown(parse_markdown(text))
    except Exception:  # any parse failure means "cannot prove equivalence"
        log.debug("write gate: markdown did not parse into the IR", exc_info=True)
        return None


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
        return Verdict(passed=False, reason="the document renders differently in mdd's model")
    return PASSED
