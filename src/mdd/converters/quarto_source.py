"""quarto_source.py — prepare a Markdown file for ``quarto render``.

Quarto treats the rendered Markdown as a program, not as data: YAML
frontmatter (and any ``---`` delimited YAML block later in the body) can name
Lua filters, external metadata files, bibliographies and include files, and
``{{< include >}}`` shortcodes splice arbitrary files into the output. The
files mdd renders were written by whoever authored the source document or
the mirror page, so none of those directives may reach Quarto.

:func:`prepare_quarto_source` rewrites the Markdown so only presentation
metadata survives:

* frontmatter keys are reduced to an explicit allow-list; everything else is
  dropped and reported,
* body lines consisting solely of ``---`` outside fenced code become ``***``
  (the same thematic break, but one Pandoc never reads as YAML),
* shortcode delimiters ``{{<`` / ``>}}`` become their escaped forms, which
  Quarto renders literally.
"""

from __future__ import annotations

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

# Keys allowed inside ``format: <name>:`` mappings.
ALLOWED_FORMAT_KEYS: frozenset[str] = frozenset(
    {
        "toc",
        "toc-depth",
        "toc-title",
        "number-sections",
        "reference-doc",
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

_YAML_DELIMITER_RE = re.compile(r"^---[ \t]*$")
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


@dataclass
class PreparedSource:
    """Result of :func:`prepare_quarto_source`."""

    text: str
    """Markdown safe to hand to ``quarto render``."""

    dropped_keys: list[str] = field(default_factory=list)
    """Frontmatter keys removed because they are not presentation metadata."""


def prepare_quarto_source(text: str) -> PreparedSource:
    """Return *text* reduced to what Quarto may act on for a plain render."""
    dropped: list[str] = []
    split = split_frontmatter(text)
    if split is None:
        body = text
        frontmatter: dict[str, Any] | None = None
    else:
        fm_block, body = split
        frontmatter = _filter_frontmatter(fm_block, dropped)

    safe_body = _neutralise_body(body)

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
        return _escape_shortcodes(value)
    if isinstance(value, list):
        return [_neutralise_value(item) for item in cast("list[object]", value)]
    if isinstance(value, dict):
        return {
            str(k): _neutralise_value(v) for k, v in cast("dict[object, object]", value).items()
        }
    return value


def _escape_shortcodes(text: str) -> str:
    return text.replace("{{<", "{{{<").replace(">}}", ">}}}")


def _neutralise_body(body: str) -> str:
    """Rewrite YAML delimiters and shortcodes outside fenced code blocks."""
    out: list[str] = []
    fence_char = ""
    fence_len = 0
    for raw_line in body.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        ending = raw_line[len(line) :]
        if fence_char:
            if _closes_fence(line, fence_char, fence_len):
                fence_char = ""
                fence_len = 0
            out.append(raw_line)
            continue
        opened = _opens_fence(line)
        if opened is not None:
            fence_char, fence_len = opened
            out.append(raw_line)
            continue
        if _YAML_DELIMITER_RE.match(line):
            out.append("***" + ending)
            continue
        out.append(_escape_shortcodes(line) + ending)
    return "".join(out)


def _opens_fence(line: str) -> tuple[str, int] | None:
    match = _FENCE_OPEN_RE.match(line)
    if match is None:
        return None
    run, info = match.group(1), match.group(2)
    if run[0] == "`" and "`" in info:
        return None
    return run[0], len(run)


def _closes_fence(line: str, fence_char: str, fence_len: int) -> bool:
    stripped = line.strip()
    return (
        len(stripped) >= fence_len
        and stripped == fence_char * len(stripped)
        and len(line) - len(line.lstrip(" ")) <= 3
    )
