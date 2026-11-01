"""Opening and continuing multi-line blocks: fences, HTML blocks, math, link
definitions and fenced divs.
"""

from __future__ import annotations

import re
from dataclasses import replace

from markdown_it.common.html_blocks import block_names

from mdd.markdown.ir.callouts import div_opener
from mdd.prose.classify.lines import Line, LineClass
from mdd.prose.classify.prefixes import (
    MD_SPACE,
    ONE_QUOTE,
    TBREAK,
    columns,
    gap_is_code,
    indent_columns,
    quote_depth,
    split_markers,
)
from mdd.prose.classify.state import State, set_block_container

_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_ATX = re.compile(r"^ {0,3}#{1,6}(\s|$)")
#: A link label: not a footnote label, not blank, no unescaped bracket, and
#: backslash escapes allowed. CommonMark's 999-character cap is not applied:
#: markdown-it does not apply it, and a long label taken for a definition
#: only keeps its line from the fixers.
_LINK_LABEL = r"\[(?!\^)(?=[ \t]*(?:[^ \t\\\[\]]|\\.))(?:[^\\\[\]]|\\.)+\]"
_LINK_DEF = re.compile(rf"^ {{0,3}}{_LINK_LABEL}:[ \t]*\S+")
_LINK_LABEL_ONLY = re.compile(rf"^ {{0,3}}{_LINK_LABEL}:[ \t]*$")
_LINK_DEF_TAIL = re.compile(rf"^ {{0,3}}{_LINK_LABEL}:[ \t]*\S+[ \t]*(.*)$")
_LINK_TITLE_START = re.compile(r"^[ \t]*[\"'(]")
HTML_BLOCK = re.compile(r"^ {0,3}</?[A-Za-z!?]")
#: HTML blocks that end at a closing marker rather than at a blank line, with
#: that marker. Each may contain blank lines, and each may interrupt a paragraph.
_HTML_RAW_BLOCKS: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    (
        re.compile(r"^ {0,3}<(?:script|pre|style|textarea)(?=[ \t>]|$)", re.IGNORECASE),
        re.compile(r"</(?:script|pre|style|textarea)>", re.IGNORECASE),
    ),
    (re.compile(r"^ {0,3}<\?"), re.compile(r"\?>")),
    (re.compile(r"^ {0,3}<![A-Za-z]"), re.compile(r">")),
    (re.compile(r"^ {0,3}<!\[CDATA\["), re.compile(r"\]\]>")),
)
#: An HTML block opened by a block-level tag name. It ends at a blank line and,
#: unlike any other tag, may interrupt a paragraph.
_HTML_BLOCK_TAG = re.compile(
    r"^ {0,3}</?(?:" + "|".join(block_names) + r")(?=[ \t]|/?>|$)", re.IGNORECASE
)
_MATH_FENCE = re.compile(r"^ {0,3}\$\$")
_MATH_LABEL_END = re.compile(r"\$\$[ \t]*\([^)$\r\n]+?\)$")
DIV_CLOSER = re.compile(r"^[ \t]*(:{3,})\s*$")


def _opens_fence(rest: str, fence: re.Match[str]) -> bool:
    """True when a fence-shaped line really opens a fenced block.

    CommonMark 4.5: the info string of a backtick fence may not contain a
    backtick. Without that condition a paragraph beginning ``` ```a `b` ``` ```
    opened a block, and everything up to the next fence-shaped line — including
    a genuine code block — became prose the fixers would rewrite.
    """
    return fence.group(1)[0] != "`" or "`" not in rest[fence.end() :]


def _closes_fence(rest: str, quote: str, state: State) -> bool:
    """True when this line closes the open fence.

    A closer must sit in the same block-quote container as the opener and be no
    more than three columns further indented. Without those two conditions a
    ``>``-prefixed or deeply indented ``` inside a fenced block closed it, and
    the remainder of the code became prose the fixers would rewrite.
    """
    fence = state.fence
    if fence is None or quote_depth(quote) != state.fence_quote_depth:
        return False
    closer = _FENCE.match(rest)
    if closer is None or closer.group(1)[0] != fence[0] or len(closer.group(1)) < len(fence):
        return False
    if indent_columns(rest) > state.fence_indent + 3:
        return False
    return not rest[closer.end() :].strip(MD_SPACE)


def _leaves_container(raw: str, depth: int, column: int) -> bool:
    """True when *raw* ends a container *depth* quotes deep, in an item at *column*.

    A fence or an HTML block is not a paragraph, so it has no lazy
    continuation: a line with fewer ``>`` than its opener ends its block
    quote, and a non-blank line indented less than its list item's content
    column ends the item, and the block with it. The indent is measured
    inside the block's own block quotes; a ``>`` beyond those is content.
    Treating either as content let a later fence-shaped line close a fence,
    and the code after that read as prose.
    """
    inside = raw
    for _ in range(depth):
        marker = ONE_QUOTE.match(inside)
        if marker is None:
            return True
        inside = inside[marker.end() :]
    return bool(inside.strip(MD_SPACE)) and indent_columns(inside) < column


def continuation(number: int, raw: str, quote: str, rest: str, state: State) -> Line | None:
    """Classify *raw* against an open multi-line construct, or return ``None``."""
    if state.in_frontmatter:
        state.in_frontmatter = rest.strip(MD_SPACE) not in ("---", "...")
        return Line(number, raw, LineClass.FRONTMATTER)
    if state.fence is not None:
        if _leaves_container(raw, state.fence_quote_depth, state.fence_container):
            state.fence = None
            return None
        if _closes_fence(rest, quote, state):
            state.fence = None
        return Line(number, raw, LineClass.FENCED_CODE)
    if state.in_comment:
        state.in_comment = "-->" not in rest
        return Line(number, raw, LineClass.HTML_COMMENT)
    return _continuation_tail(number, raw, rest, state)


def _closes_math(text: str) -> bool:
    """True when *text* ends a math block: it ends in ``$$``, or in ``$$`` and a label.

    The closer need not be alone on its line: ``c $$`` ends the block, and so
    the line after it is not maths. A trailing no-break space is content, so
    ``$$`` followed by one does not close the block; closing early hands the
    rest of the maths to the fixers as prose.
    """
    stripped = text.strip(MD_SPACE)
    return stripped.endswith("$$") or _MATH_LABEL_END.search(stripped) is not None


def _continuation_tail(number: int, raw: str, rest: str, state: State) -> Line | None:
    """The second half of :func:`continuation`: math blocks and HTML blocks."""
    if state.in_math:
        state.in_math = not _closes_math(rest)
        return Line(number, raw, LineClass.MATH)
    if not state.in_html_block:
        return None
    if _leaves_container(raw, state.html_quote_depth, state.html_container):
        state.in_html_block = False
        return None
    if state.html_end is not None:
        state.in_html_block = state.html_end.search(rest) is None
        return Line(number, raw, LineClass.HTML_BLOCK)
    if rest.strip(MD_SPACE):
        return Line(number, raw, LineClass.HTML_BLOCK)
    state.in_html_block = False
    return Line(number, raw, LineClass.BLANK)


def _open_html_block(rest: str, state: State) -> bool:
    """Open an HTML block at *rest* if one starts there, and say whether it did.

    Mirrors CommonMark's seven kinds closely enough to fail closed. ``<pre>``,
    ``<script>``, processing instructions and the like run to their closing
    marker, blank lines included; ending them at the first blank line handed
    their tail to the fixers as prose. Those kinds and the block-level tag names
    may interrupt a paragraph. Any other tag-shaped line opens a block only
    after a blank line, so a mid-paragraph ``<https://…>`` stays prose.
    """
    for opener, end in _HTML_RAW_BLOCKS:
        opened = opener.match(rest)
        if opened is not None:
            state.in_html_block = end.search(rest, opened.end()) is None
            state.html_end = end
            return True
    if _HTML_BLOCK_TAG.match(rest) or (not state.in_paragraph and HTML_BLOCK.match(rest)):
        state.in_html_block = True
        state.html_end = None
        return True
    return False


def open_block(number: int, raw: str, quote: str, rest: str, state: State) -> Line | None:
    """Classify *raw* as the opening line of a multi-line construct, or ``None``."""
    fence = _FENCE.match(rest)
    if fence is not None and _opens_fence(rest, fence):
        state.fence = fence.group(1)
        state.fence_quote_depth = quote_depth(quote)
        state.fence_indent = indent_columns(rest)
        state.fence_container = 0
        state.open_at = number
        return Line(number, raw, LineClass.FENCED_CODE)
    stripped = rest.lstrip()
    if stripped.startswith("<!--"):
        # The closer may share the opener's dashes: `<!-->` and `<!--->` are
        # whole comments.
        if "-->" not in stripped[2:]:
            state.in_comment = True
            state.open_at = number
        return Line(number, raw, LineClass.HTML_COMMENT)
    if _MATH_FENCE.match(rest):
        # A math block is one line only when the opener carries its own closer;
        # `$$`, `$$$` and `$$ a` all open a block that runs to a later line.
        if len(rest.strip(MD_SPACE)) <= len("$$$") or not _closes_math(rest):
            state.in_math = True
            state.open_at = number
        return Line(number, raw, LineClass.MATH)
    # A fenced-div opener. Its body is ordinary prose and is reflowed; the
    # marker line is not. Joining `:::callout-tip` into the paragraph below it
    # destroys the callout, which is a first-class construct in the IR. A
    # colon run with a name the renderer does not know is paragraph text.
    fence = div_opener(rest.lstrip(MD_SPACE))
    if fence is not None:
        state.divs.append((fence, quote_depth(quote)))
        return Line(number, raw, LineClass.DIV_MARKER)
    if _open_html_block(rest, state):
        state.html_quote_depth = quote_depth(quote)
        state.html_container = 0
        return Line(number, raw, LineClass.HTML_BLOCK)
    return None


def single_line_class(rest: str) -> LineClass | None:
    """Return the class of a line that is a whole block by itself, or ``None``."""
    if _ATX.match(rest):
        return LineClass.HEADING
    if TBREAK.match(rest):
        return LineClass.THEMATIC_BREAK
    if _LINK_DEF.match(rest) or _LINK_LABEL_ONLY.match(rest):
        return LineClass.LINK_DEF
    return None


def _unclosed_title(rest: str) -> bool:
    """True when the link definition on *rest* opens a title it does not close."""
    tail = _LINK_DEF_TAIL.match(rest)
    if tail is None:
        return False
    title = tail.group(1).rstrip(MD_SPACE)
    if not title or title[0] not in "\"'(":
        return False
    closer = ")" if title[0] == "(" else title[0]
    return len(title) < 2 or title[-1] != closer


def link_definition(line: Line, rest: str, state: State) -> Line:
    """Extend a link reference definition over the lines that continue it.

    A definition may put its destination, or its title, on a later line, and a
    title may run over several. Reproducing that grammar is not worth it, so
    this fails closed: once a definition is incomplete, every line that would
    otherwise be paragraph text is called part of it until something else ends
    the run. A paragraph glued to a definition loses its checks; no line of a
    definition is ever handed to a fixer.
    """
    continues = state.in_link_def or (
        state.after_link_def and _LINK_TITLE_START.match(rest) is not None
    )
    if line.cls is LineClass.PROSE and continues:
        line = Line(line.number, line.text, LineClass.LINK_DEF)
        state.in_link_def = True
    elif line.cls is LineClass.LINK_DEF:
        split = split_markers(rest)
        definition = (split[2] if split is not None else rest).lstrip(MD_SPACE)
        state.in_link_def = bool(_LINK_LABEL_ONLY.match(definition)) or _unclosed_title(definition)
    else:
        state.in_link_def = False
    state.after_link_def = line.cls is LineClass.LINK_DEF
    return line


def marker_line(number: int, raw: str, quote: str, rest: str, state: State) -> Line | None:
    """Classify a list item or footnote line by the block its content opens.

    The content after a marker is the first block of a new item, so it may be
    anything a line on its own may be: a heading, a rule, a fence, maths, an
    HTML block, a link definition, indented code, or nothing at all. Calling
    those prose handed them to the fixers. ``None`` when the content is
    paragraph text, or *rest* carries no marker.
    """
    split = split_markers(rest)
    if split is None:
        return None
    markers, gap, content = split
    prefix = quote + markers
    if not content.strip(MD_SPACE):
        return Line(number, raw, LineClass.LIST_MARKER, prefix=prefix)
    # Tabs in the gap expand from the column the marker ends at.
    if gap_is_code(markers, gap):
        return Line(number, raw, LineClass.INDENTED_CODE, prefix=prefix)
    # Nothing the content opens is interrupting a paragraph: it is the first
    # line of the item. The scan loop recomputes this flag after every line.
    state.in_paragraph = False
    opened = open_block(number, raw, prefix, content, state)
    if opened is not None:
        set_block_container(opened, columns(markers), state)
        return replace(opened, prefix=prefix)
    single = single_line_class(content)
    return Line(number, raw, single, prefix=prefix) if single is not None else None


def close_div(number: int, raw: str, quote: str, rest: str, state: State) -> Line | None:
    """Classify a bare colon run that may close an open fenced div, or ``None``.

    The renderer closes a div at the first line that is exactly its colon run,
    at any indent. A run that matches no open div is paragraph text. One whose
    block-quote depth differs from its opener's may still close it, through a
    lazy continuation line, so it is a marker but leaves the div open.
    """
    closer = DIV_CLOSER.match(rest)
    if closer is None:
        return None
    fence = closer.group(1)
    depth = quote_depth(quote)
    if (fence, depth) in state.divs:
        del state.divs[state.divs.index((fence, depth)) :]
    elif not any(open_fence == fence for open_fence, _ in state.divs):
        return None
    return Line(number, raw, LineClass.DIV_MARKER)
