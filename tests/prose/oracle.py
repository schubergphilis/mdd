"""An oracle for prose writers, deliberately independent of :mod:`mdd.prose`.

It parses with markdown-it-py directly, in mdd's own flavour plus the front
matter, footnote and dollar-math plugins, and never asks the production code
what a line is. Two implementations that agree are evidence; one
implementation checked against itself is not.

A rewrite must also leave cmark-gfm's rendering alone. That is the renderer
GitHub uses, and markdown-it departs from CommonMark in places, so a rewrite
markdown-it cannot tell apart may still change a page on GitHub.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from cmarkgfm.cmark import (  # pyright: ignore[reportMissingTypeStubs]
    Options,
    markdown_to_html_with_extensions,  # pyright: ignore[reportUnknownVariableType]
)
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin

from mdd.markdown.ir.flavour import build_md

if TYPE_CHECKING:
    from markdown_it import MarkdownIt
    from markdown_it.token import Token

#: Block tokens whose content is literal. A writer must not change one byte.
VERBATIM_TOKENS = frozenset(
    {"fence", "code_block", "html_block", "math_block", "math_block_label", "front_matter"}
)

#: Markdown's own whitespace. Not `\s`: a no-break space is content.
_MD_WHITESPACE = re.compile(r"[ \t\r\n]+")

#: Elements whose whitespace is kept byte for byte, the same set the write gate
#: keeps. ``code``, ``kbd`` and ``samp`` collapse whitespace in a browser;
#: counting them is the conservative choice.
_LITERAL_ELEMENT = re.compile(
    r"(<(pre|code|kbd|samp|textarea|listing|xmp)(?=[\s>/])[^>]*>.*?</\2\s*>)",
    re.DOTALL | re.IGNORECASE,
)


def oracle_parser() -> MarkdownIt:
    """The mdd flavour, plus the syntax extensions a prose file may carry.

    The footnote plugin normally moves definitions to the end of the document
    and drops the ones nothing references, taking their source map with them.
    Keeping them where they were written means an edit inside an unreferenced
    footnote still shows up in the rendered output.
    """
    md = build_md().use(front_matter_plugin).use(footnote_plugin).use(dollarmath_plugin)
    return md.disable("footnote_tail")


PARSER = oracle_parser()


def oracle_lines(text: str) -> list[str]:
    """Split *text* into source lines the way markdown-it numbers them."""
    return re.split(r"\r\n|\r|\n", text)


def rendered(text: str) -> str:
    """Render *text* to HTML with insignificant whitespace runs collapsed.

    A soft line break and a space render identically, which is what lets a
    reflow move one. Inside ``<pre>``, ``<code>`` and the other elements in
    :data:`_LITERAL_ELEMENT` whitespace is content, so those are kept byte for
    byte.
    """
    return _collapse(PARSER.render(text))


#: GFM as GitHub renders it, raw HTML included, less the tag filter, which
#: escapes ``<xmp>`` and the like and would hide changes inside them.
_CMARK_OPTIONS = cast(
    "int",
    Options.CMARK_OPT_UNSAFE | Options.CMARK_OPT_FOOTNOTES,  # pyright: ignore[reportUnknownMemberType]
)
_CMARK_EXTENSIONS = ["table", "strikethrough", "autolink", "tasklist"]


def commonmark_rendered(text: str) -> str:
    """Render *text* with cmark-gfm, insignificant whitespace collapsed as in :func:`rendered`."""
    html = cast(
        "str",
        markdown_to_html_with_extensions(
            text, options=_CMARK_OPTIONS, extensions=_CMARK_EXTENSIONS
        ),
    )
    return _collapse(html)


def _collapse(html: str) -> str:
    # Each match yields two groups: the element, then its name.
    parts = _LITERAL_ELEMENT.split(html)
    out: list[str] = []
    for index, part in enumerate(parts):
        if index % 3 == 0:
            out.append(_MD_WHITESPACE.sub(" ", part))
        elif index % 3 == 1:
            out.append(part)
    return "".join(out).strip()


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
    for token in PARSER.parse(text):
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
    assert commonmark_rendered(after) == commonmark_rendered(before), (
        "the CommonMark rendering changed"
    )


# --- reasons that are safe to print -------------------------------------------
#
# A corpus can be private. These say where and what kind of thing changed, by
# line number and token type, and never quote the text.


def difference(before: str, after: str) -> str | None:
    """Why *after* does not mean what *before* meant, or ``None`` when it does.

    The same judgement as :func:`assert_same_document`, phrased without
    quoting either document.
    """
    if before == after:
        return None
    old_blocks, new_blocks = verbatim_blocks(before), verbatim_blocks(after)
    if old_blocks != new_blocks:
        return _literal_change(old_blocks, new_blocks)
    if rendered(before) != rendered(after):
        line = _changed_block_line(before, after)
        return f"the rendered document changed, first in the block at line {line}"
    if commonmark_rendered(before) != commonmark_rendered(after):
        return "the CommonMark rendering changed"
    return None


def first_changed_line(before: str, after: str) -> int:
    """The one-based number of the first source line that differs."""
    old, new = oracle_lines(before), oracle_lines(after)
    for number, (old_line, new_line) in enumerate(zip(old, new, strict=False), start=1):
        if old_line != new_line:
            return number
    return min(len(old), len(new)) + 1


def _literal_change(before: list[Verbatim], after: list[Verbatim]) -> str:
    for ordinal, (old, new) in enumerate(zip(before, after, strict=False), start=1):
        if old != new:
            return f"literal block {ordinal} of {len(before)} ({old.kind}) changed"
    return f"the number of literal blocks went from {len(before)} to {len(after)}"


def _blocks(text: str) -> list[tuple[int, str]]:
    """Each top-level block of *text*: its first source line and its collapsed HTML."""
    env: dict[str, object] = {}
    tokens = PARSER.parse(text, env)
    out: list[tuple[int, str]] = []
    start = 0
    for index, token in enumerate(tokens):
        if token.level != 0 or token.nesting > 0:
            continue
        group = tokens[start : index + 1]
        line = group[0].map[0] + 1 if group[0].map is not None else 0
        html = str(PARSER.renderer.render(group, PARSER.options, env))
        out.append((line, _collapse(html)))
        start = index + 1
    return out


def _changed_block_line(before: str, after: str) -> int:
    """The source line in *before* of the first top-level block that renders differently."""
    old, new = _blocks(before), _blocks(after)
    for (line, old_html), (_, new_html) in zip(old, new, strict=False):
        if old_html != new_html:
            return line
    if len(old) > len(new):
        return old[len(new)][0]
    return first_changed_line(before, after)
