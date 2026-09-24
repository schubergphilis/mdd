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

import html
import re
from dataclasses import dataclass, field
from typing import Any, cast

import yaml

from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter

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
# Python regular expressions below see the same line boundaries.
_LINE_TERMINATOR_RE = re.compile(r"\r\n|[\r\u2028\u2029]")

# JavaScript's ``\s``. Python's also matches NEL and the C0 separators, which
# would make a fence closer followed by one of those count as code here but
# not for Quarto.
_JS_WHITESPACE = r"\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"

# The three regular expressions Quarto applies, in this order, to find YAML
# blocks in a Markdown document.
_HTML_COMMENT_RE = re.compile(r"<!--[\W\w]*?-->")
_BACKTICK_FENCE_RE = re.compile(
    r"^([\t >]*`{3,})[^`\n]*\n[\W\w]*?\n\1[" + _JS_WHITESPACE + r"]*$", re.MULTILINE
)
_YAML_BLOCK_RE = re.compile(
    r"^(---)[ \t]*\n+(?![ \t]*\n+)[\W\w]*?\n+(?:---|\.\.\.)[ \t]*$", re.MULTILINE
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


def prepare_quarto_source(text: str) -> PreparedSource:
    """Return *text* reduced to what Quarto may act on for a plain render.

    Line endings are normalised to LF and a leading byte-order mark is
    removed; the result is only ever written to a temporary file for Quarto.
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
    """Escape shortcodes in a metadata string, including entity and backslash spellings."""
    plain = _ESCAPED_DELIMITER_CHAR_RE.sub(r"\1", html.unescape(text))
    return _escape_shortcodes(plain)


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
        without_comments, comment_map = _remove_spans(text, _HTML_COMMENT_RE)
        view, fence_map = _remove_spans(without_comments, _BACKTICK_FENCE_RE)
        openers = [m.start(1) for m in _YAML_BLOCK_RE.finditer(view)]
        if not openers:
            return text
        for start in openers:
            for offset in range(3):
                chars[comment_map[fence_map[start + offset]]] = "*"


def _remove_spans(text: str, pattern: re.Pattern[str]) -> tuple[str, list[int]]:
    """Delete every *pattern* match from *text*.

    Returns the shortened text and, for each character of it, that character's
    index in *text*.
    """
    kept: list[int] = []
    pos = 0
    for match in pattern.finditer(text):
        kept.extend(range(pos, match.start()))
        pos = match.end()
    kept.extend(range(pos, len(text)))
    return "".join(text[i] for i in kept), kept
