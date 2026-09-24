"""Make text from mirrors and remote services safe to print to a terminal.

Page bodies, titles, config paths and server messages can carry escape
sequences that a terminal would act on: moving the cursor, erasing lines,
hiding text or reordering it. Anything built from such content is passed
through these helpers before it is printed or logged, so the operator sees
what mdd saw.
"""

from __future__ import annotations

import re

# C0 controls except TAB (\x09) and LF (\x0a), DEL, C1 controls, and the
# explicit bidi embedding/override/isolate controls (U+202A..U+202E,
# U+2066..U+2069), which reorder how a terminal displays the rest of the line.
# CR is replaced: on its own it returns the cursor and lets later text
# overwrite the line.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\x80-\x9f\u202a-\u202e\u2066-\u2069]")
_CONTROL_PLACEHOLDER = "\ufffd"


def neutralise_controls(text: str) -> str:
    """Replace terminal control and bidi override characters in *text* with U+FFFD.

    Each control character maps to exactly one placeholder, so offsets
    computed on the original string remain valid. Tabs and newlines are kept.
    """
    return _CONTROL_CHARS_RE.sub(_CONTROL_PLACEHOLDER, text)


def neutralise_lines(text: str) -> str:
    """Neutralise multi-line *text*, treating CRLF line ends as line breaks.

    Like :func:`neutralise_controls`, except that a ``\\r`` ending a line
    (CRLF content) is dropped rather than shown as a placeholder. A ``\\r``
    anywhere else is still replaced. Newlines, including a trailing one,
    are kept.
    """
    return "\n".join(neutralise_controls(line.removesuffix("\r")) for line in text.split("\n"))


# Everything neutralise_controls replaces, plus the characters that start a
# new line: LF, and the Unicode line and paragraph separators. VT, FF, CR and
# NEL are already in the control ranges above.
_LINE_BREAKING_RE = re.compile(r"[\n\u2028\u2029]")


def neutralise_line(text: str) -> str:
    """Neutralise *text* that is shown inside a single line, such as a title or path.

    Like :func:`neutralise_controls`, except that line breaks are replaced
    too, so a value interpolated into a one-line message cannot start a new
    line of its own. Tabs are kept and each replaced character maps to one
    placeholder.
    """
    return _LINE_BREAKING_RE.sub(_CONTROL_PLACEHOLDER, neutralise_controls(text))
