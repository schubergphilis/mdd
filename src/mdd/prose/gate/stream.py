"""Flattening a markdown-it token stream into items the gate can compare."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin

from mdd.markdown.ir.flavour import build_md
from mdd.prose.gate.literal import LITERAL_ELEMENT_START, LiteralTracker

if TYPE_CHECKING:
    from collections.abc import Sequence

    from markdown_it import MarkdownIt
    from markdown_it.token import Token

#: Runs of Markdown whitespace. Deliberately ASCII only: a no-break space is a
#: typographic choice, and collapsing it would let a writer silently drop one.
_MARKDOWN_WHITESPACE = re.compile(r"[ \t\r\n]+")

#: How a footnote definition's tokens change the footnote nesting depth.
_FOOTNOTE_NESTING = {"footnote_reference_open": 1, "footnote_reference_close": -1}


@dataclass(frozen=True)
class Item:
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


def _inline_footnotes(env: dict[str, Any]) -> dict[int, list[Token]]:
    """Return the parsed body of every inline footnote, by footnote id.

    The footnote plugin keeps these out of the token stream.
    """
    notes: dict[int, dict[str, Any]] = env.get("footnotes", {}).get("list", {})
    return {number: note["tokens"] for number, note in notes.items() if "tokens" in note}


class _InlineFlattener:
    """Turns one inline token's children into comparable items.

    *tracker* is ``None`` when the document has no whitespace-preserving
    element at all. Text inside a footnote is literal whenever it has one.
    """

    def __init__(
        self,
        line: int,
        tracker: LiteralTracker | None,
        footnotes: dict[int, list[Token]],
        *,
        in_footnote: bool = False,
    ) -> None:
        self.line = line
        self.items: list[Item] = []
        self._text: list[str] = []
        self._text_line = line
        self._tracker = tracker
        self._footnotes = footnotes
        self._in_footnote = in_footnote

    def _literal(self) -> bool:
        tracker = self._tracker
        return tracker is not None and (self._in_footnote or tracker.literal)

    def _flush(self) -> None:
        if self._text:
            if self._literal():
                joined = "".join(self._text)
                kind = "html_literal_text"
            else:
                joined = _collapse("".join(self._text))
                kind = "text"
            self.items.append(Item(kind, (kind,), joined, self._text_line))
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
            self.items.append(Item(child.type, _shape(child), "", self.line))
            self.feed(child.children)
            self._flush()
            return
        # Everything else keeps its content byte for byte. That is the point
        # for code spans, math and inline HTML, and fails closed for any plugin
        # token this module does not know about.
        self.items.append(Item(child.type, _shape(child), child.content, self.line))
        self.line += 1 if child.type == "hardbreak" else child.content.count("\n")
        self._track(child)
        if child.type == "footnote_ref":
            self._feed_inline_footnote(child)

    def _track(self, child: Token) -> None:
        tracker = self._tracker
        if tracker is None:
            return
        if child.type == "html_inline":
            if self._in_footnote:
                tracker.feed_out_of_place(child.content)
            else:
                tracker.feed(child.content)
        elif child.type.startswith("math"):
            tracker.feed_math(child.content)

    def _feed_inline_footnote(self, child: Token) -> None:
        body = self._footnotes.get(child.meta.get("id", -1))
        if body is None:
            return
        nested = _InlineFlattener(self.line, self._tracker, self._footnotes, in_footnote=True)
        nested.feed(body)
        self.items.extend(nested.finish())
        self.line = nested.line

    def finish(self) -> list[Item]:
        """Flush pending text and strip the whitespace at either end."""
        self._flush()
        items = self.items
        if items and items[0].type == "text":
            first = items[0]
            items[0] = Item("text", first.key, first.literal.lstrip(" "), first.line)
        if items and items[-1].type == "text":
            last = items[-1]
            items[-1] = Item("text", last.key, last.literal.rstrip(" "), last.line)
        return [item for item in items if item.type != "text" or item.literal]


class TooDeep(Exception):
    """The parser reached its nesting limit, past which it drops content unseen."""

    def __init__(self, line: int) -> None:
        super().__init__(line)
        self.line = line


def _check_nesting(token: Token, line: int) -> None:
    """Raise :class:`TooDeep` when *token* sits where the parser stops looking.

    markdown-it stops tokenizing blocks once its nesting level reaches
    ``maxNesting`` and silently drops everything below that point, so two
    documents that differ only down there compare equal. It does not report
    that it gave up; a block that opens one level short of the limit is the
    sign, since its content is parsed at the limit.
    """
    if token.nesting == 1 and token.level >= _parser().options["maxNesting"] - 1:
        raise TooDeep(line)


def _track_block(tracker: LiteralTracker, token: Token, *, in_footnote: bool) -> None:
    if token.type == "html_block":
        if in_footnote:
            tracker.feed_out_of_place(token.content)
        else:
            tracker.feed(token.content)
    elif token.type.startswith("math"):
        tracker.feed_math(token.content)


def items(text: str) -> list[Item]:
    """Flatten *text*'s token stream into comparable items.

    Footnotes are compared where they are written. Inline footnotes, which
    are kept out of the stream, are compared where they are referenced.
    """
    env: dict[str, Any] = {}
    tokens = _parser().parse(text, env)
    footnotes = _inline_footnotes(env)
    tracker = LiteralTracker() if LITERAL_ELEMENT_START.search(text) else None
    items: list[Item] = []
    line = 1
    footnote_depth = 0
    for token in tokens:
        if token.map is not None:
            line = token.map[0] + 1
        _check_nesting(token, line)
        footnote_depth += _FOOTNOTE_NESTING.get(token.type, 0)
        if token.type == "inline":
            flattener = _InlineFlattener(line, tracker, footnotes, in_footnote=footnote_depth > 0)
            flattener.feed(token.children or [])
            items.extend(flattener.finish())
            continue
        if tracker is not None:
            _track_block(tracker, token, in_footnote=footnote_depth > 0)
        items.append(Item(token.type, _shape(token), token.content, line))
    return items
