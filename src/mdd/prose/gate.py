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
from typing import TYPE_CHECKING, Any

from markdown_it.common import html_re
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

#: Elements a browser renders with their whitespace intact, so text inside one
#: is compared byte for byte. ``code``, ``kbd`` and ``samp`` collapse
#: whitespace in a browser; counting them is the conservative choice. So is
#: counting ``script``, ``style`` and the other elements whose text is not
#: shown at all.
_LITERAL_ELEMENTS = frozenset(
    {
        "code",
        "iframe",
        "kbd",
        "listing",
        "noembed",
        "noframes",
        "noscript",
        "plaintext",
        "pre",
        "samp",
        "script",
        "style",
        "textarea",
        "title",
        "xmp",
    }
)
#: Elements whose content is text up to their own end tag: no tag inside one
#: opens or closes anything. ``plaintext`` has no end tag at all.
_RAW_TEXT_ELEMENTS = frozenset(
    {"iframe", "noembed", "noframes", "noscript", "script", "style", "textarea", "title", "xmp"}
)
_RAW_TEXT_END = {
    name: re.compile(rf"</{name}(?=[\t\n\f\r />])", re.IGNORECASE) for name in _RAW_TEXT_ELEMENTS
}
#: The start of a tag that opens a whitespace-preserving element, wherever it
#: appears. A document without one has no such element anywhere.
_LITERAL_ELEMENT_START = re.compile(
    rf"<(?:{'|'.join(sorted(_LITERAL_ELEMENTS))})(?=[\s/>]|\Z)", re.IGNORECASE
)
#: One HTML construct, as markdown-it recognises inline HTML. ``opaque`` are
#: the constructs a browser ends at a different place than markdown-it does.
_HTML_CONSTRUCT = re.compile(
    f"(?P<open>{html_re.open_tag})|(?P<close>{html_re.close_tag})"
    f"|(?P<comment>{html_re.comment})|(?P<declaration>{html_re.declaration})"
    f"|(?P<opaque>{html_re.processing}|{html_re.cdata})",
    re.ASCII,
)
#: How a footnote definition's tokens change the footnote nesting depth.
_FOOTNOTE_NESTING = {"footnote_reference_open": 1, "footnote_reference_close": -1}
_TAG_NAME = re.compile(r"</?([A-Za-z][A-Za-z0-9-]*)")
#: Where a browser starts reading a tag, comment or other markup.
_MARKUP_START = re.compile(r"<[A-Za-z!?/]")

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
    "html_literal_text": "run of preformatted HTML text",
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


def _comment_ends_where_a_browser_ends_it(comment: str) -> bool:
    """Whether a browser ends *comment* at its last character, as markdown-it does.

    A browser ends a comment at the first ``-->`` or ``--!>``; markdown-it's
    pattern can run on past either.
    """
    ends = [at + len(end) for end in ("-->", "--!>") if (at := comment.find(end, 2)) >= 0]
    return min(ends, default=-1) == len(comment)


class _LiteralTracker:
    """Which whitespace-preserving HTML elements a browser would have open.

    An element may open in one paragraph or HTML block and close in a later
    one, so a single tracker follows the whole token stream. It fails closed:
    when the HTML is anything it cannot follow the way a browser would, it
    takes every element to stay open until the end of the document.
    """

    def __init__(self) -> None:
        self._open: list[str] = []
        self._to_the_end = False

    @property
    def literal(self) -> bool:
        """Whether text at this point renders with its whitespace intact."""
        return self._to_the_end or bool(self._open)

    def feed(self, html: str) -> None:
        """Follow raw HTML as a browser would read it, from where the last left off."""
        position = 0
        while not self._to_the_end and position < len(html):
            if self._open and self._open[-1] in _RAW_TEXT_ELEMENTS:
                position = self._skip_raw_text(html, position)
            else:
                position = self._take_construct(html, position)

    def feed_out_of_place(self, html: str) -> None:
        """Follow HTML that renders somewhere other than where it is written.

        A footnote renders after the body, or in place without the footnote
        plugin. Neither position can be trusted, so a whitespace-preserving tag
        in one keeps everything after it literal.
        """
        if _LITERAL_ELEMENT_START.search(html):
            self._to_the_end = True

    def feed_math(self, math: str) -> None:
        """Follow math, which a renderer without the math plugin reads as Markdown.

        Any markup in it might then open, close or hide a tag.
        """
        if _MARKUP_START.search(math):
            self._to_the_end = True

    def _skip_raw_text(self, html: str, position: int) -> int:
        name = self._open[-1]
        end = _RAW_TEXT_END[name].search(html, position)
        stop = len(html) if end is None else end.start()
        if name == "script" and "<!--" in html[position:stop]:
            # Inside a script, a comment opener changes where the script ends.
            self._to_the_end = True
        if end is None:
            return len(html)
        _ = self._open.pop()
        return stop

    def _take_construct(self, html: str, position: int) -> int:
        start = html.find("<", position)
        if start < 0:
            return len(html)
        construct = _HTML_CONSTRUCT.match(html, start)
        if construct is None:
            # Markup markdown-it would not take as a tag, such as an unclosed
            # comment or a quote that never closes, but a browser reads anyway.
            if _MARKUP_START.match(html, start):
                self._to_the_end = True
            return start + 1
        kind = construct.lastgroup
        text = construct.group()
        if kind == "open":
            self._open_element(self._name(text))
        elif kind == "close":
            self._close_element(self._name(text))
        elif kind == "opaque" or (
            kind == "comment" and not _comment_ends_where_a_browser_ends_it(text)
        ):
            self._to_the_end = True
        return construct.end()

    @staticmethod
    def _name(tag: str) -> str:
        name = _TAG_NAME.match(tag)
        return name.group(1).lower() if name else ""

    def _open_element(self, name: str) -> None:
        # A trailing slash does not close a non-void element in HTML.
        if name == "plaintext":
            self._to_the_end = True
        elif name in _LITERAL_ELEMENTS:
            self._open.append(name)

    def _close_element(self, name: str) -> None:
        # A browser ignores an end tag for an element that is not open.
        if name in self._open:
            del self._open[len(self._open) - 1 - self._open[::-1].index(name)]


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
        tracker: _LiteralTracker | None,
        footnotes: dict[int, list[Token]],
        *,
        in_footnote: bool = False,
    ) -> None:
        self.line = line
        self.items: list[_Item] = []
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
            self.items.append(_Item(kind, (kind,), joined, self._text_line))
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


class _TooDeep(Exception):
    """The parser reached its nesting limit, past which it drops content unseen."""

    def __init__(self, line: int) -> None:
        super().__init__(line)
        self.line = line


def _check_nesting(token: Token, line: int) -> None:
    """Raise :class:`_TooDeep` when *token* sits where the parser stops looking.

    markdown-it stops tokenizing blocks once its nesting level reaches
    ``maxNesting`` and silently drops everything below that point, so two
    documents that differ only down there compare equal. It does not report
    that it gave up; a block that opens one level short of the limit is the
    sign, since its content is parsed at the limit.
    """
    if token.nesting == 1 and token.level >= _parser().options["maxNesting"] - 1:
        raise _TooDeep(line)


def _track_block(tracker: _LiteralTracker, token: Token, *, in_footnote: bool) -> None:
    if token.type == "html_block":
        if in_footnote:
            tracker.feed_out_of_place(token.content)
        else:
            tracker.feed(token.content)
    elif token.type.startswith("math"):
        tracker.feed_math(token.content)


def _items(text: str) -> list[_Item]:
    """Flatten *text*'s token stream into comparable items.

    Footnotes are compared where they are written. Inline footnotes, which
    are kept out of the stream, are compared where they are referenced.
    """
    env: dict[str, Any] = {}
    tokens = _parser().parse(text, env)
    footnotes = _inline_footnotes(env)
    tracker = _LiteralTracker() if _LITERAL_ELEMENT_START.search(text) else None
    items: list[_Item] = []
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
        elif old.type == "html_literal_text":
            reason = "the text inside a whitespace-preserving HTML element changed"
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
    except _TooDeep as deep:
        return Verdict(
            passed=False, line=deep.line, reason="the document nests too deeply to compare"
        )
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
