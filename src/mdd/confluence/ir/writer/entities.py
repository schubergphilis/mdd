"""Attribute helpers and HTML-entity re-substitution for the writer.

Names without a leading underscore are shared across sibling modules
inside ``mdd.confluence.ir.writer``. Names with an underscore stay
local to this module. The package boundary is the encapsulation
surface.
"""

from __future__ import annotations

import html.entities
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape, quoteattr

if TYPE_CHECKING:
    from mdd.ir.nodes import Text


def emit_attrs(attributes: dict[str, str]) -> str:
    """Emit attributes in source order, skipping internal marker keys (leading ``_``)."""
    if not attributes:
        return ""
    return "".join(f" {k}={quoteattr(v)}" for k, v in attributes.items() if not k.startswith("_"))


_XML_PREDEFINED_DECODES = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&apos;": "'",
}


def _decode_entity(entity_str: str) -> str:
    """Decode any entity reference back to its character (HTML5 + XML)."""
    if entity_str in _XML_PREDEFINED_DECODES:
        return _XML_PREDEFINED_DECODES[entity_str]
    name = entity_str[1:-1] + ";"
    return html.entities.html5.get(name, "")


def render_preserved_text(content: str, entity_form: dict[int, str], out: list[str]) -> None:
    """Emit `content` with each `entity_form[offset]` substituted at offset.

    The text between entities is XML-escaped via `escape()` so any `<`, `>`
    or `&` literal in `content` round-trips as `&lt;` / `&gt;` / `&amp;`.
    """
    if not entity_form:
        out.append(escape(content))
        return
    parts: list[str] = []
    pos = 0
    for offset in sorted(entity_form.keys()):
        entity_str = entity_form[offset]
        char = _decode_entity(entity_str)
        char_len = len(char) if char else 1
        if offset >= len(content):
            continue
        parts.append(escape(content[pos:offset]))
        parts.append(entity_str)
        pos = offset + char_len
    parts.append(escape(content[pos:]))
    out.append("".join(parts))


def render_text_preserving(tok: Text, out: list[str]) -> None:
    """Emit ``Text.content`` re-substituting original entities from ``Origin.entity_form``."""
    if tok.origin is None:
        out.append(escape(tok.content))
        return
    render_preserved_text(tok.content, tok.origin.entity_form, out)
