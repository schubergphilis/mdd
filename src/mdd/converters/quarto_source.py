"""quarto_source.py — prepare a Markdown file for ``quarto render``.

Quarto treats the rendered Markdown as a program, not as data: YAML
frontmatter (and any ``---`` delimited YAML block later in the body) can name
Lua filters, external metadata files, bibliographies and include files, and
``{{< … >}}`` shortcodes read environment variables or splice files into the
output. The files mdd renders were written by whoever authored the source
document or the mirror page, so none of those directives may reach Quarto.

:func:`prepare_quarto_source` rewrites the Markdown so only presentation
metadata survives:

* frontmatter keys are reduced to an explicit allow-list; everything else is
  dropped and reported,
* every ``---`` line that Quarto's own metadata scanner would take as the start
  of a YAML block becomes ``***`` (the same thematic break, never read as
  YAML),
* shortcode delimiters ``{{<`` / ``>}}`` become their escaped forms everywhere,
  including inside code, because Quarto expands shortcodes in code blocks and
  inline code too.

Quarto does not use a Markdown parser to find metadata blocks. It strips HTML
comments, then strips backtick fences whose closing line repeats the opening
line's prefix exactly, and searches what is left with a regular expression
anchored at line starts. Tilde fences, fences inside list items and fences
whose closing indentation differs are *not* code to that scanner, so this
module reproduces the scanner instead of tracking CommonMark fences.
"""

from __future__ import annotations

import bisect
import html
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import yaml

from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping

log = get_logger(__name__)

# Top-level frontmatter keys that only affect presentation.
ALLOWED_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "title",
        "subtitle",
        "author",
        "date",
        "abstract",
        "lang",
        "toc",
        "toc-depth",
        "toc-title",
        "number-sections",
        "format",
    }
)

# Keys allowed inside ``format: <name>:`` mappings. ``reference-doc`` is not
# among them: it names a file Quarto opens, and mdd supplies the template on
# the command line where one is wanted.
ALLOWED_FORMAT_KEYS: frozenset[str] = frozenset(
    {
        "toc",
        "toc-depth",
        "toc-title",
        "number-sections",
        "slide-level",
        "incremental",
        "fig-width",
        "fig-height",
        "fig-align",
        "page-width",
    }
)

# mdd's own frontmatter blocks. Quarto ignores them, so dropping them is not
# worth a warning.
_TOOL_OWNED_KEYS: frozenset[str] = frozenset({"sharepoint", "confluence", "publish_office", "pptx"})

# Quarto's scanner runs in JavaScript, where ``^`` and ``$`` in multiline mode
# also break on CR, U+2028 and U+2029. Everything is folded to LF first so the
# Python code below sees the same line boundaries.
_LINE_TERMINATOR_RE = re.compile(r"\r\n|[\r\u2028\u2029]")

# JavaScript's ``\s`` without LF. Python's ``str.isspace`` also matches NEL and
# the C0 separators, which would make a fence closer followed by one of those
# count as code here but not for Quarto.
_JS_WHITESPACE_NO_LF = (
    "\t\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009"
    "\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)

# Characters Quarto allows before the backticks of a fence line.
_FENCE_PREFIX_CHARS = "\t >"

# Unescaping a metadata string more often than this means it was built to
# nest encodings; see :func:`_neutralise_metadata_string`.
_MAX_UNESCAPE_PASSES = 8

# Quarto finds YAML blocks in three steps: it removes HTML comments
# (``<!--[\W\w]*?-->``), then backtick fences
# (``^([\t >]*`{3,})[^`\n]*\n[\W\w]*?\n\1\s*$`` with JavaScript's ``\s``), then
# searches the rest with the expression below. The first two are reproduced by
# linear scanners (:func:`_html_comment_spans`, :func:`_backtick_fence_spans`):
# as regular expressions they rescan to the end of the text from every opener
# that has no closer. Quarto's own YAML expression has ``\n+`` before the
# closer; a single ``\n`` finds the same blocks, because the lazy part before
# it can take the other line breaks, and does not retry every length of a long
# run of blank lines.
_YAML_BLOCK_RE = re.compile(
    r"^(---)[ \t]*\n+(?![ \t]*\n+)[\W\w]*?\n(?:---|\.\.\.)[ \t]*$", re.MULTILINE
)

# Pandoc reads metadata strings as Markdown, so these forms of ``{`` ``<``
# ``>`` ``}`` reach Quarto's shortcode handler as the bare characters.
_ESCAPED_DELIMITER_CHAR_RE = re.compile(r"\\([{}<>])")


@dataclass
class PreparedSource:
    """Result of :func:`prepare_quarto_source`."""

    text: str
    """Markdown safe to hand to ``quarto render``."""

    dropped_keys: list[str] = field(default_factory=list)
    """Frontmatter keys removed because they are not presentation metadata."""


def prepare_quarto_source(
    text: str, *, extra_metadata: Mapping[str, object] | None = None
) -> PreparedSource:
    """Return *text* reduced to what Quarto may act on for a plain render.

    Line endings are normalised to LF and a leading byte-order mark is
    removed; the result is only ever written to a temporary file for Quarto.

    *extra_metadata* is mdd's own frontmatter for the render (for example the
    filters mdd runs). It is added after the author's keys are filtered, as
    given, and overrides an author key of the same name.
    """
    dropped: list[str] = []
    text = _LINE_TERMINATOR_RE.sub("\n", text.removeprefix("\ufeff"))
    split = split_frontmatter(text)
    if split is None:
        body = text
        frontmatter: dict[str, Any] | None = None
    else:
        fm_block, body = split
        frontmatter = _filter_frontmatter(fm_block, dropped)

    safe_body = _escape_shortcodes(_neutralise_yaml_blocks(body))

    if extra_metadata:
        frontmatter = {**(frontmatter or {}), **extra_metadata}

    if not frontmatter:
        return PreparedSource(text=safe_body, dropped_keys=dropped)

    fm_text = yaml.safe_dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return PreparedSource(text=f"---\n{fm_text}---\n{safe_body}", dropped_keys=dropped)


def _filter_frontmatter(fm_block: str, dropped: list[str]) -> dict[str, Any] | None:
    mapping = parse_yaml_mapping(fm_block)
    if mapping is None:
        return None
    kept: dict[str, Any] = {}
    for key, value in mapping.items():
        if key in _TOOL_OWNED_KEYS:
            continue
        if key not in ALLOWED_TOP_LEVEL_KEYS:
            dropped.append(str(key))
            continue
        if _reuses_containers(value):
            log.warning("frontmatter key %r reuses a YAML anchor for a list or mapping", key)
            dropped.append(str(key))
            continue
        if key == "format":
            kept[key] = _filter_format(value, dropped)
        else:
            kept[key] = _neutralise_value(value)
    return kept


def _filter_format(value: object, dropped: list[str]) -> object:
    """Keep ``format: docx`` as-is and filter ``format: {docx: {...}}`` mappings."""
    if not isinstance(value, dict):
        return _neutralise_value(value)
    formats: dict[str, object] = {}
    for fmt_name, options in cast("dict[object, object]", value).items():
        if not isinstance(options, dict):
            formats[str(fmt_name)] = _neutralise_value(options)
            continue
        kept_options: dict[str, object] = {}
        for opt, opt_value in cast("dict[object, object]", options).items():
            if opt in ALLOWED_FORMAT_KEYS:
                kept_options[str(opt)] = _neutralise_value(opt_value)
            else:
                dropped.append(f"format.{fmt_name}.{opt}")
        formats[str(fmt_name)] = kept_options
    return formats


def _reuses_containers(value: object) -> bool:
    """Return whether *value* reaches the same list or mapping twice.

    That only happens through YAML aliases. Each alias is a few characters but
    stands for a whole copy of its anchor, so nested aliases make a short
    frontmatter expand exponentially (or loop, for an anchor that contains its
    own alias) once :func:`_neutralise_value` copies it.
    """
    seen: set[int] = set()
    pending: list[object] = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            children = list(cast("dict[object, object]", item).values())
        elif isinstance(item, list):
            children = list(cast("list[object]", item))
        else:
            continue
        identity = id(cast("object", item))
        if identity in seen:
            return True
        seen.add(identity)
        pending.extend(children)
    return False


def _neutralise_value(value: object) -> object:
    """Escape shortcode delimiters inside every string scalar of *value*."""
    if isinstance(value, str):
        return _neutralise_metadata_string(value)
    if isinstance(value, list):
        return [_neutralise_value(item) for item in cast("list[object]", value)]
    if isinstance(value, dict):
        return {
            str(k): _neutralise_value(v) for k, v in cast("dict[object, object]", value).items()
        }
    return value


def _neutralise_metadata_string(text: str) -> str:
    """Escape shortcodes in a metadata string, including entity and backslash spellings.

    Pandoc decodes one more layer of entities and backslash escapes when it
    reads the string, so decoding only once would turn ``&amp;lt;`` into a
    live ``<``. Decoding repeats until the text stops changing. A string that
    is still changing after a few passes is built from nested encodings; its
    ``&`` and ``\\`` are removed so nothing is left for pandoc to decode.
    """
    for _ in range(_MAX_UNESCAPE_PASSES):
        decoded = _ESCAPED_DELIMITER_CHAR_RE.sub(r"\1", html.unescape(text))
        if decoded == text:
            return _escape_shortcodes(text)
        text = decoded
    log.warning("metadata string nests encodings too deeply; removing its '&' and '\\'")
    return _escape_shortcodes(text.replace("&", "").replace("\\", ""))


def _escape_shortcodes(text: str) -> str:
    return text.replace("{{<", "{{{<").replace(">}}", ">}}}")


def _neutralise_yaml_blocks(body: str) -> str:
    """Turn every ``---`` that Quarto would read as the start of a YAML block into ``***``.

    Works on Quarto's view of the text (comments and backtick fences removed)
    and maps each match back to the original characters, so a delimiter that
    only lines up after a comment is removed is caught as well. Repeats until
    the scanner finds nothing, because removing one block can expose the next.
    """
    chars = list(body)
    while True:
        text = "".join(chars)
        without_comments, comment_map = _remove_spans(text, _html_comment_spans(text))
        view, fence_map = _remove_spans(without_comments, _backtick_fence_spans(without_comments))
        openers = [m.start(1) for m in _YAML_BLOCK_RE.finditer(view)]
        if not openers:
            return text
        for start in openers:
            for offset in range(3):
                chars[comment_map[fence_map[start + offset]]] = "*"


def _html_comment_spans(text: str) -> list[tuple[int, int]]:
    """Return the spans Quarto removes as HTML comments, left to right.

    Once an opener has no closer, no later opener has one either, so the scan
    stops there instead of trying every remaining opener.
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    while (start := text.find("<!--", pos)) != -1:
        closer = text.find("-->", start + 4)
        if closer == -1:
            break
        pos = closer + 3
        spans.append((start, pos))
    return spans


def _fence_opener_prefix(line: str) -> str | None:
    """Return the indentation and backtick run of a fence opener line, or None.

    An opener is optional tabs, spaces and ``>``, at least three backticks,
    then anything without a backtick. The returned prefix is what the closing
    line has to start with.
    """
    end = len(line)
    ticks_start = 0
    while ticks_start < end and line[ticks_start] in _FENCE_PREFIX_CHARS:
        ticks_start += 1
    ticks_end = ticks_start
    while ticks_end < end and line[ticks_end] == "`":
        ticks_end += 1
    if ticks_end - ticks_start < 3 or "`" in line[ticks_end:]:
        return None
    return line[:ticks_end]


def _backtick_fence_spans(text: str) -> list[tuple[int, int]]:
    """Return the spans Quarto removes as backtick fences, left to right.

    A fence runs from an opener line to the first line at least two lines
    further down that is the opener's prefix followed only by whitespace. The
    span also takes the whitespace-only lines after the closer, up to the last
    line break before the next non-blank line or the end of the text.
    """
    lines = text.split("\n")
    starts: list[int] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line) + 1

    closers: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        key = line.rstrip(_JS_WHITESPACE_NO_LF)
        if key.endswith("```"):
            closers.setdefault(key, []).append(index)

    spans: list[tuple[int, int]] = []
    last = len(lines) - 1
    index = 0
    # The last line has no line break after it, so it cannot open a fence.
    while index < last:
        prefix = _fence_opener_prefix(lines[index])
        candidates = closers.get(prefix, []) if prefix is not None else []
        found = bisect.bisect_left(candidates, index + 2)
        if found == len(candidates):
            index += 1
            continue
        end_line = candidates[found]
        while end_line < last and not lines[end_line + 1].strip(_JS_WHITESPACE_NO_LF):
            end_line += 1
        end = len(text) if end_line == last else starts[end_line] + len(lines[end_line])
        spans.append((starts[index], end))
        index = end_line + 1
    return spans


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> tuple[str, list[int]]:
    """Delete the ordered, non-overlapping *spans* from *text*.

    Returns the shortened text and, for each character of it, that character's
    index in *text*.
    """
    kept: list[int] = []
    pos = 0
    for start, end in spans:
        kept.extend(range(pos, start))
        pos = end
    kept.extend(range(pos, len(text)))
    return "".join(text[i] for i in kept), kept
