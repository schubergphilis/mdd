"""HTML named-entity decoding pass."""

from __future__ import annotations

import html.entities
import re
from dataclasses import replace
from typing import TYPE_CHECKING

from ..nodes import (
    Inline,
    Text,
)
from ._map import transform_text_blocks

if TYPE_CHECKING:
    from ..document import Document

# Safe subset: named HTML entities that map to a single Unicode character and
# whose Unicode form is readable. Excludes entities that could cause confusion
# (e.g. &nbsp; → U+00A0 looks like space but isn't).
_ENTITY_WHITELIST: dict[str, str] = {
    "hellip": "…",
    "mdash": "—",
    "ndash": "–",
    "lsquo": "‘",
    "rsquo": "’",
    "ldquo": "“",
    "rdquo": "”",
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "apos": "'",
    "copy": "©",
    "reg": "®",
    "trade": "™",
    "euro": "€",
    "pound": "£",
    "yen": "¥",
    "cent": "¢",
    "deg": "°",
    "plusmn": "±",
    "times": "×",
    "divide": "÷",
    "frac12": "½",
    "frac14": "¼",
    "frac34": "¾",
    "rarr": "→",
    "larr": "←",
    "uarr": "↑",
    "darr": "↓",
    "harr": "↔",
    "bull": "•",
    "middot": "·",
    "prime": "′",
    "Prime": "″",
    "laquo": "«",
    "raquo": "»",
}

_ENTITY_RE = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")


def _decode_entities(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        char = _ENTITY_WHITELIST.get(name)
        if char is not None:
            return char
        # Also check the full html5 entity table for completeness.
        char2 = html.entities.html5.get(name + ";")
        return char2 if char2 is not None else m.group(0)

    return _ENTITY_RE.sub(repl, text)


def _decode_entities_in_inlines(inlines: list[Inline]) -> list[Inline]:
    return [
        replace(tok, content=_decode_entities(tok.content))  # type: ignore[call-overload]
        if isinstance(tok, Text) and "&" in tok.content
        else tok
        for tok in inlines
    ]


def normalise_entities(doc: Document) -> Document:
    """Convert safe HTML named entities in ``Text`` content to Unicode."""
    return transform_text_blocks(doc, _decode_entities_in_inlines)
