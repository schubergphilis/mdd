"""Following the whitespace-preserving HTML elements a browser would have open.

Text inside one of these elements is compared byte for byte, so the gate must
know where each one opens and closes the way a browser reads the HTML.
"""

from __future__ import annotations

import re

from markdown_it.common import html_re

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
LITERAL_ELEMENT_START = re.compile(
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
_TAG_NAME = re.compile(r"</?([A-Za-z][A-Za-z0-9-]*)")
#: Where a browser starts reading a tag, comment or other markup.
_MARKUP_START = re.compile(r"<[A-Za-z!?/]")


def _comment_ends_where_a_browser_ends_it(comment: str) -> bool:
    """Whether a browser ends *comment* at its last character, as markdown-it does.

    A browser ends a comment at the first ``-->`` or ``--!>``; markdown-it's
    pattern can run on past either.
    """
    ends = [at + len(end) for end in ("-->", "--!>") if (at := comment.find(end, 2)) >= 0]
    return min(ends, default=-1) == len(comment)


class LiteralTracker:
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
        if LITERAL_ELEMENT_START.search(html):
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
