"""Hypothesis strategies that build hostile Markdown documents from block-level pieces.

Every block strategy returns a :class:`Block`: its source lines (without line
terminators) and a short name for what it is meant to be. The document
strategy joins blocks with blank-line runs of varying length, sometimes with
none at all so that one block has to interrupt or continue another, and then
picks a line ending and whether the file ends with one.

The names are a hint, not a promise. "almost-setext" is a paragraph followed by
a line that nearly underlines it, and whether a given draw lands on the near or
the far side of that line is exactly what the oracle is for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hypothesis import strategies as st

if TYPE_CHECKING:
    from collections.abc import Sequence

NBSP = "\xa0"

#: Characters that look like a plain space and are not one.
INVISIBLE = (NBSP, "\u2007", "\u2009", "\u200a", "\u200b", "\u202f", "\u3000", "\ufeff")

#: The suppression comment, with the rule ids a writer acts on.
SUPPRESSED_RULES = (
    "trailing-whitespace",
    "multiple-spaces",
    "space-before-punctuation",
    "blank-run",
    "reflow",
)

_WORDS = (
    "the",
    "parser",
    "reads",
    "every",
    "line",
    "and",
    "then",
    "decides",
    "what",
    "block",
    "it",
    "belongs",
    "to",
    "while",
    "writer",
    "keeps",
    "bytes",
    "intact",
    "configuration",
    "Confluence",
    "page",
    "section",
    "because",
    "however",
    "which",
    "although",
    "document",
    "markdown",
    "rendered",
    "output",
    "x",
    "a",
    "I",
)

#: Inline tokens that are either hard to segment into sentences or that turn
#: into a block construct if a rewrite moves them to the start of a line.
_HOSTILE = (
    "e.g.",
    "i.e.,",
    "Dr.",
    "etc.",
    "vs.",
    "U.S.",
    "No. 5",
    "3.14",
    "...",
    "…",
    "(a parenthetical, with a comma. And a stop.)",
    '"A quoted sentence. Another one."',
    "“smart quotes.”",
    "'single quoted',",
    "`code span`",
    "`` a ` b ``",
    "`a  b`",
    "[a link](https://example.com/a_b)",
    "[ref][label]",
    "[label]",
    "<https://example.com/x>",
    "https://example.com/plain",
    "*emphasis*",
    "**strong words**",
    "_under_score_",
    "~~struck~~",
    "<span>inline</span>",
    "<br>",
    "$x + y$",
    "\\*",
    "\\",
    "&amp;",
    "&nbsp;",
    "1.",
    "2)",
    "10.",
    "-",
    "+",
    "*",
    "#",
    "##",
    ">",
    "|",
    "a | b",
    "---",
    "===",
    "```",
    "~~~",
    ":::",
    "$$",
    "<div>",
    "<!--",
    "-->",
    "<!-- note -->",
    "[^1]",
    "[^1]:",
    "[x]:",
    "OSC 9 ; 4",
    "word ,",
    "word  word",
    "ends .",
    "./configs",
    ":80",
    f"no{NBSP}break",
    "zero\u200bwidth",
    "thin\u2009space",
)

_TERMINATORS = (".", ".", ".", "?", "!", ":", ";", "", ".)", '."', ".”")


@dataclass(frozen=True)
class Block:
    """Source lines for one block, and what the generator meant it to be."""

    kind: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Document:
    """One generated file, and the names of the blocks that went into it."""

    text: str
    kinds: tuple[str, ...]


# --- inline text ------------------------------------------------------------


def _word() -> st.SearchStrategy[str]:
    return st.one_of(
        st.sampled_from(_WORDS),
        st.sampled_from(_WORDS),
        st.sampled_from(_HOSTILE),
    )


@st.composite
def sentence(draw: st.DrawFn) -> str:
    """One sentence, often long, salted with abbreviations, quotes and markup."""
    words = draw(st.lists(_word(), min_size=2, max_size=40))
    separators = draw(
        st.lists(
            st.sampled_from((" ",) * 12 + ("  ", "\t", NBSP, " ;", " ,")),
            min_size=len(words) - 1,
            max_size=len(words) - 1,
        )
    )
    text = words[0]
    for separator, word in zip(separators, words[1:], strict=True):
        text += separator + word
    first = text[0].upper() + text[1:]
    return first + draw(st.sampled_from(_TERMINATORS))


@st.composite
def wrapped(draw: st.DrawFn, *, min_sentences: int = 1, max_sentences: int = 4) -> list[str]:
    """Sentences joined into one string and hard-wrapped at arbitrary word boundaries."""
    sentences = draw(st.lists(sentence(), min_size=min_sentences, max_size=max_sentences))
    words = " ".join(sentences).split(" ")
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        if draw(st.integers(0, 9)) == 0:
            lines.append(" ".join(current))
            current = []
    if current:
        lines.append(" ".join(current))
    return [line for line in lines if line.strip(" \t")] or ["Fallback text."]


@st.composite
def line_ending(draw: st.DrawFn, line: str) -> str:
    """Decorate *line* with trailing whitespace, a hard break, or nothing."""
    tail = draw(
        st.sampled_from(("", "", "", "", " ", "  ", "   ", "\t", " \t", "\\", NBSP, "  " + NBSP))
    )
    return line + tail


# --- leaf blocks ------------------------------------------------------------


@st.composite
def paragraph(draw: st.DrawFn) -> Block:
    """A hard-wrapped paragraph whose lines may carry trailing whitespace or breaks."""
    lines = draw(wrapped())
    decorated = [draw(line_ending(line)) for line in lines]
    if draw(st.integers(0, 7)) == 0:
        index = draw(st.integers(0, len(decorated) - 1))
        decorated[index] = draw(st.sampled_from(INVISIBLE)) + decorated[index]
    return Block("paragraph", tuple(decorated))


@st.composite
def atx_heading(draw: st.DrawFn) -> Block:
    """An ATX heading, sometimes with a closing sequence or a lead indent."""
    level = draw(st.integers(1, 6))
    indent = draw(st.sampled_from(("", "", " ", "   ")))
    text = draw(sentence())
    closing = draw(st.sampled_from(("", "", " #", " ###")))
    return Block("atx-heading", (f"{indent}{'#' * level} {text}{closing}",))


@st.composite
def setext_heading(draw: st.DrawFn) -> Block:
    """A paragraph underlined with ``===`` or ``---``."""
    lines = draw(wrapped(max_sentences=2))
    char = draw(st.sampled_from("=-"))
    underline = (
        draw(st.sampled_from(("", " ", "   ")))
        + char * draw(st.integers(1, 12))
        + draw(st.sampled_from(("", " ", "  ")))
    )
    return Block("setext-heading", (*lines, underline))


@st.composite
def almost_setext(draw: st.DrawFn) -> Block:
    """A paragraph followed by a line that nearly, or only just, underlines it."""
    lines = draw(wrapped(max_sentences=2))
    underline = draw(
        st.sampled_from(
            (
                "- - -",
                "--- x",
                "    ---",
                "==a",
                "= =",
                "-- -",
                "\t===",
                f"{NBSP}===",
                "***",
                "___",
                "-",
                "=",
                "   -",
                "- foo",
            )
        )
    )
    return Block("almost-setext", (*lines, underline))


@st.composite
def thematic_break(draw: st.DrawFn) -> Block:
    """A thematic break in one of its many spellings."""
    return Block(
        "thematic-break",
        (draw(st.sampled_from(("***", "---", "___", " * * *", "- - -", "_____", "   ***"))),),
    )


_CODE_BODY = (
    "def f(x):  ",
    "    return x  # trailing  ",
    "",
    "<!--",
    "-->",
    "$$",
    ":::",
    "- not a list",
    "> not a quote",
    "# not a heading",
    "a  b ,c",
    "``",
    "~~",
    "   ```",
    "    ```",
    "~~~~~~~~",
    "```````",
    f"{NBSP}```",
    "\tindented with a tab",
    "| a | b |",
    "<div>",
)


@st.composite
def code_body(draw: st.DrawFn) -> list[str]:
    """Literal lines that would be something else outside a code block."""
    return draw(
        st.lists(
            st.one_of(st.sampled_from(_CODE_BODY), sentence()),
            min_size=0,
            max_size=5,
        )
    )


@st.composite
def fenced_code(draw: st.DrawFn, *, allow_unclosed: bool = False) -> Block:
    """A fenced code block: backtick or tilde, of varying length, with an info string."""
    char = draw(st.sampled_from("`~"))
    length = draw(st.integers(3, 6))
    indent = draw(st.sampled_from(("", "", "", " ", "  ", "   ")))
    info = draw(
        st.sampled_from(("", "", "python", " yaml", "c++ {.x}", "a `b`", "~~~", "x  y  ", "```"))
    )
    opener = f"{indent}{char * length}{info}"
    body = draw(code_body())
    if allow_unclosed and draw(st.integers(0, 3)) == 0:
        return Block("unclosed-fence", (opener, *body))
    closer_length = length + draw(st.integers(0, 2))
    closer_indent = draw(st.sampled_from(("", "", " ", "   ")))
    closer = closer_indent + char * closer_length + draw(st.sampled_from(("", "", " ", "\t")))
    return Block("fenced-code", (opener, *body, closer))


@st.composite
def indented_code(draw: st.DrawFn) -> Block:
    """An indented code block, with interior blank lines and tab indents."""
    count = draw(st.integers(1, 5))
    lines: list[str] = []
    for _ in range(count):
        indent = draw(st.sampled_from(("    ", "    ", "\t", "  \t", "      ", " \t")))
        body = draw(st.one_of(st.sampled_from(_CODE_BODY), sentence()))
        lines.append(indent + body if body else "")
    if not lines[0]:
        lines[0] = "    x = 1"
    while not lines[-1]:
        lines.pop()
    return Block("indented-code", tuple(lines))


@st.composite
def html_block(draw: st.DrawFn) -> Block:
    """An HTML block of one of the seven CommonMark kinds.

    Kinds 1 to 5 end at their own end condition rather than at a blank line, so
    their bodies may contain blank lines and text that reads like a paragraph.
    """
    prose = draw(wrapped(max_sentences=2))
    blank_inside = draw(st.booleans())
    inner = [*prose, "", *prose] if blank_inside else prose
    kind = draw(st.integers(1, 7))
    match kind:
        case 1:
            tag = draw(st.sampled_from(("pre", "script", "style", "textarea")))
            lines = (f"<{tag}>", *inner, f"</{tag}>")
        case 2:
            lines = ("<!--", *inner, "-->")
        case 3:
            lines = ("<?php", *inner, "?>")
        case 4:
            lines = ("<!DOCTYPE html>",)
        case 5:
            lines = ("<![CDATA[", *inner, "]]>")
        case 6:
            tag = draw(st.sampled_from(("div", "table", "details", "p", "section", "DIV")))
            lines = (f"<{tag}>", *prose, f"</{tag}>")
        case _:
            tag = draw(st.sampled_from(('<span class="x">', "<custom-tag>", "<a href='x'>")))
            lines = (tag, *prose)
    return Block(f"html-block-{kind}", lines)


@st.composite
def html_comment(draw: st.DrawFn) -> Block:
    """An HTML comment on one line, or spread over several."""
    text = draw(sentence())
    if draw(st.booleans()):
        return Block("html-comment", (f"<!-- {text} -->",))
    return Block("html-comment", ("<!--", text, "  more  text  ", "-->"))


@st.composite
def suppression(draw: st.DrawFn) -> Block:
    """An ``mdd-prose-ignore`` comment, ahead of the block it suppresses."""
    rule = draw(st.sampled_from(SUPPRESSED_RULES))
    form = draw(
        st.sampled_from(
            (
                f"<!-- mdd-prose-ignore: {rule} -->",
                "<!-- mdd-prose-ignore -->",
                f"<!-- mdd-prose-ignore-file: {rule} -->",
                "<!-- mdd-prose-ignore: no-such-rule -->",
            )
        )
    )
    target = draw(paragraph())
    return Block("suppression", (form, *target.lines))


@st.composite
def table(draw: st.DrawFn) -> Block:
    """A GFM table, with or without outer pipes."""
    columns = draw(st.integers(1, 4))
    outer = draw(st.booleans())

    def row(cells: list[str]) -> str:
        body = " | ".join(cells)
        return f"| {body} |" if outer else body

    words = st.sampled_from((*_WORDS, "`a | b`", "x  y", "end ."))
    header = row(draw(st.lists(words, min_size=columns, max_size=columns)))
    delimiter = row(
        draw(
            st.lists(
                st.sampled_from(("---", ":--", "--:", ":-:", "-")),
                min_size=columns,
                max_size=columns,
            )
        )
    )
    if columns == 1 and not outer:
        delimiter = "| --- |"
        header = f"| {header} |"
    body_rows = [
        row(draw(st.lists(words, min_size=columns, max_size=columns)))
        for _ in range(draw(st.integers(0, 3)))
    ]
    return Block("table", (header, delimiter, *body_rows))


@st.composite
def front_matter(draw: st.DrawFn) -> Block:
    """YAML front matter, closed by ``---`` or (rarely) by ``...``."""
    keys = draw(
        st.lists(
            st.sampled_from(
                (
                    "title: A  title ,with spaces  ",
                    "tags: [a, b]",
                    "last-verified: 2026-01-01",
                    "description: >",
                    "  folded  text .",
                    "",
                    "# a comment",
                )
            ),
            min_size=0,
            max_size=4,
        )
    )
    closer = draw(st.sampled_from(("---", "---", "---", "...")))
    return Block("front-matter", ("---", *keys, closer))


@st.composite
def math_block(draw: st.DrawFn) -> Block:
    """A ``$$`` display-math block, multi-line or on one line."""
    body = draw(st.lists(st.sampled_from(("x  =  1 ,", "a + b", "\\frac{1}{2}", "")), max_size=3))
    if draw(st.integers(0, 3)) == 0:
        return Block("math-inline-block", ("$$ x + y $$",))
    return Block("math-block", ("$$", *body, "$$"))


@st.composite
def link_definition(draw: st.DrawFn) -> Block:
    """A link reference definition, on one line or spread over three."""
    label = draw(st.sampled_from(("label", "x", "a b", "Label")))
    if draw(st.booleans()):
        return Block("link-def", (f'[{label}]: https://example.com/{label[0]} "A  title ."',))
    return Block("link-def", (f"[{label}]:", "  https://example.com/x", '  "A title  ."'))


@st.composite
def footnote_definition(draw: st.DrawFn) -> Block:
    """A footnote definition with an indented continuation."""
    lines = draw(wrapped(max_sentences=2))
    indent = draw(st.sampled_from(("    ", "  ", "")))
    return Block("footnote-def", (f"[^1]: {lines[0]}", *(indent + line for line in lines[1:])))


def leaf_block() -> st.SearchStrategy[Block]:
    """Any block that contains no other block."""
    return st.one_of(
        paragraph(),
        paragraph(),
        paragraph(),
        atx_heading(),
        setext_heading(),
        almost_setext(),
        thematic_break(),
        fenced_code(),
        indented_code(),
        html_block(),
        html_comment(),
        suppression(),
        table(),
        math_block(),
        link_definition(),
        footnote_definition(),
    )


# --- container blocks -------------------------------------------------------


def _join(blocks: Sequence[Block], blank_runs: Sequence[int]) -> list[str]:
    lines: list[str] = list(blocks[0].lines)
    for block, blanks in zip(blocks[1:], blank_runs, strict=True):
        lines.extend([""] * blanks)
        lines.extend(block.lines)
    return lines


@st.composite
def block_sequence(draw: st.DrawFn, depth: int, *, max_size: int = 3) -> list[str]:
    """Several blocks separated by blank-line runs, sometimes zero lines long."""
    blocks = draw(st.lists(any_block(depth), min_size=1, max_size=max_size))
    blank_runs = draw(
        st.lists(
            st.sampled_from((1, 1, 1, 0, 2)),
            min_size=len(blocks) - 1,
            max_size=len(blocks) - 1,
        )
    )
    return _join(blocks, blank_runs)


@st.composite
def list_block(draw: st.DrawFn, depth: int) -> Block:
    """A bullet or ordered list, with varied indents, tabs and lazy continuations."""
    ordered = draw(st.booleans())
    bullet = draw(st.sampled_from("-*+"))
    delimiter = draw(st.sampled_from(".)"))
    start = draw(st.sampled_from((1, 1, 3, 9, 10, 123456789)))
    outer = draw(st.sampled_from(("", "", " ", "  ", "   ")))
    loose = draw(st.booleans())
    out: list[str] = []
    for number in range(start, start + draw(st.integers(1, 3))):
        marker = f"{number}{delimiter}" if ordered else bullet
        gap = draw(st.sampled_from((" ", " ", " ", "  ", "    ", "\t")))
        lead = outer + marker + gap
        body = draw(block_sequence(depth - 1, max_size=2))
        out.append(lead + body[0])
        width = len(lead) if "\t" not in gap else len(outer + marker) + 3
        skew = draw(st.sampled_from((0, 0, 0, 1, -1, 2)))
        indent = " " * max(0, width + skew)
        if draw(st.integers(0, 5)) == 0:
            indent = "\t" + " " * max(0, width - 4)
        for line in body[1:]:
            lazy = draw(st.integers(0, 6)) == 0
            out.append(line if (lazy or not line) else indent + line)
        if loose:
            out.append("")
    while out and not out[-1]:
        out.pop()
    return Block("ordered-list" if ordered else "bullet-list", tuple(out))


@st.composite
def block_quote(draw: st.DrawFn, depth: int) -> Block:
    """A block quote around other blocks, sometimes with lazy continuation lines."""
    body = draw(block_sequence(depth - 1, max_size=2))
    marker = draw(st.sampled_from((">", "> ", "> ", ">  ", " > ", "> > ")))
    out: list[str] = []
    for index, line in enumerate(body):
        lazy = index > 0 and bool(line) and draw(st.integers(0, 6)) == 0
        if lazy:
            out.append(line)
        elif not line:
            out.append(marker.rstrip(" ") if draw(st.booleans()) else marker)
        else:
            out.append(marker + line)
    return Block("block-quote", tuple(out))


@st.composite
def fenced_div(draw: st.DrawFn, depth: int) -> Block:
    """A ``:::`` fenced div (callout or layout) around other blocks."""
    colons = draw(st.sampled_from((":::", ":::", "::::")))
    name = draw(st.sampled_from(("callout-tip", "callout-note", "layout", "unknown-name")))
    body = draw(block_sequence(depth - 1, max_size=2))
    pad = [""] if draw(st.booleans()) else []
    return Block("fenced-div", (f"{colons} {name}", *pad, *body, *pad, colons))


def any_block(depth: int) -> st.SearchStrategy[Block]:
    """A leaf block or, while *depth* allows, a container around more blocks."""
    if depth <= 0:
        return leaf_block()
    return st.one_of(
        leaf_block(),
        list_block(depth),
        block_quote(depth),
        fenced_div(depth),
    )


@st.composite
def unclosed_block(draw: st.DrawFn) -> Block:
    """A construct that never closes: CommonMark runs it to the end of the file."""
    body = draw(wrapped(max_sentences=2))
    kind = draw(st.sampled_from(("fence", "comment", "math", "front-matter")))
    match kind:
        case "fence":
            opener = draw(st.sampled_from(("```", "~~~~", "```python")))
            return Block("unclosed-fence", (opener, *body))
        case "comment":
            return Block("unclosed-comment", ("<!--", *body))
        case "math":
            return Block("unclosed-math", ("$$", *body))
        case _:
            return Block("unclosed-front-matter", ("---", "title: x"))


# --- documents --------------------------------------------------------------


@st.composite
def documents(draw: st.DrawFn, *, allow_unclosed: bool = False) -> Document:
    """A whole file: optional front matter, blocks, blank runs, line endings."""
    blocks: list[Block] = []
    if draw(st.integers(0, 4)) == 0:
        blocks.append(draw(front_matter()))
    blocks.extend(draw(st.lists(any_block(2), min_size=1, max_size=6)))
    if allow_unclosed and draw(st.booleans()):
        tail = draw(unclosed_block())
        if tail.kind == "unclosed-front-matter":
            blocks.insert(0, tail)
        else:
            blocks.append(tail)
    blank_runs = draw(
        st.lists(
            st.sampled_from((1, 1, 1, 1, 0, 2, 3)),
            min_size=len(blocks) - 1,
            max_size=len(blocks) - 1,
        )
    )
    lines = _join(blocks, blank_runs)
    if draw(st.integers(0, 4)) == 0:
        lines = [line or draw(st.sampled_from(("", " ", "\t", "  "))) for line in lines]
    if draw(st.integers(0, 5)) == 0:
        lines.extend([""] * draw(st.integers(1, 3)))
    newline = draw(st.sampled_from(("\n", "\n", "\n", "\r\n")))
    final = draw(st.integers(0, 5)) != 0
    text = newline.join(lines) + (newline if final else "")
    return Document(text=text, kinds=tuple(block.kind for block in blocks))
