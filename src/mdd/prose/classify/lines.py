"""The classifier's result types, and splitting a file into lines and back."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mdd.prose.inline import LinkRef, Span


class LineClass(StrEnum):
    """What one source line is."""

    FRONTMATTER = "frontmatter"
    FENCED_CODE = "fenced-code"
    INDENTED_CODE = "indented-code"
    HTML_BLOCK = "html-block"
    HTML_COMMENT = "html-comment"
    TABLE = "table"
    BLOCK_QUOTE = "block-quote"
    HEADING = "heading"
    THEMATIC_BREAK = "thematic-break"
    LINK_DEF = "link-target"
    MATH = "math"
    BLANK = "blank"
    #: A ``:::``/``::::`` fenced-div marker (callouts, layouts). Its body is
    #: ordinary prose and is reflowed; the marker line itself never is.
    DIV_MARKER = "div-marker"
    #: A region a rewriter must pass through byte-for-byte: an mdd-managed
    #: export callout, or a callout marker line such as ``> [!NOTE]``. Joining
    #: one into the paragraph below it changes what the file renders as.
    MANAGED = "managed-region"
    #: A list item or footnote marker line whose content is not paragraph text:
    #: an empty item, whose content, if any, starts on a later line.
    LIST_MARKER = "list-marker"
    #: A line markdown-it and CommonMark renderers such as GitHub's read
    #: differently, so that an edit safe for one may change the other, or a
    #: blank line only one of them counts. Passed through byte for byte.
    DIVERGENT = "divergent"
    PROSE = "prose"


@dataclass(frozen=True)
class Line:
    """One classified source line.

    ``prefix`` is the leading bytes a rewriter must preserve verbatim — block
    quote markers, a list marker, the indent. ``cont_prefix`` is what a
    generated continuation line must start with so the block still parses.
    """

    number: int
    text: str
    cls: LineClass
    prefix: str = ""
    cont_prefix: str = ""
    masks: tuple[Span, ...] = ()
    links: tuple[LinkRef, ...] = ()
    block: int = -1
    hard_break: bool = False
    #: The block-quote markers the scan found at the start of the line.
    quote: str = ""

    @property
    def content(self) -> str:
        """The line's text with its preserved prefix removed."""
        return self.text[len(self.prefix) :]


@dataclass(frozen=True)
class Classified:
    """A whole file's classification, plus the byte-level facts a writer needs."""

    lines: tuple[Line, ...]
    newline: str
    final_newline: bool


@dataclass(frozen=True)
class ClassifyError:
    """Why a file could not be classified.

    A value rather than an exception: one unparseable file must not end a
    corpus-wide run.
    """

    line: int
    reason: str


def newline_style(text: str) -> str | None:
    """Return the file's single line-ending convention, or ``None`` if it mixes them.

    Splitting on one terminator when the file uses two leaves the other embedded
    inside a "line", so the classifier mis-scans it and a rewriter silently drops
    or moves bytes. There is no correct choice to make on the user's behalf, so a
    mixed file fails closed instead.
    """
    crlf = text.count("\r\n")
    counts = {
        "\r\n": crlf,
        "\n": text.count("\n") - crlf,
        "\r": text.count("\r") - crlf,
    }
    present = [style for style, count in counts.items() if count]
    if len(present) > 1:
        return None
    return present[0] if present else "\n"


def split_lines(text: str) -> tuple[list[str], str, bool]:
    """Split *text* into lines, returning its newline and whether one trails."""
    newline = newline_style(text) or "\n"
    final_newline = text.endswith(newline)
    body = text[: -len(newline)] if final_newline else text
    if not body and final_newline:
        return [], newline, True
    return body.split(newline), newline, final_newline


def join_lines(lines: list[str], newline: str, *, final_newline: bool) -> str:
    """Inverse of :func:`split_lines`."""
    body = newline.join(lines)
    return body + newline if final_newline else body
