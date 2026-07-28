"""Whitespace and empty-paragraph normalisation passes."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from ..nodes import (
    Block,
    Inline,
    Paragraph,
    SoftBreak,
    Text,
)
from ._map import filter_blocks, transform_text_blocks

if TYPE_CHECKING:
    from ..document import Document


def _collapse_inlines_soft_breaks(inlines: list[Inline]) -> list[Inline]:
    return [Text(" ") if isinstance(tok, SoftBreak) else tok for tok in inlines]


def collapse_soft_breaks(doc: Document) -> Document:
    """Replace every ``SoftBreak`` inside a ``Paragraph`` with ``Text(" ")``."""
    return transform_text_blocks(doc, _collapse_inlines_soft_breaks)


def _collapse_internal_ws(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text)


def _normalise_text_token(tok: Text, *, lstrip: bool, rstrip: bool) -> Text:
    new_content = _collapse_internal_ws(tok.content)
    if lstrip:
        new_content = new_content.lstrip()
    if rstrip:
        new_content = new_content.rstrip()
    return replace(tok, content=new_content) if new_content != tok.content else tok


def _normalise_inlines_ws(inlines: list[Inline]) -> list[Inline]:
    last = len(inlines) - 1
    return [
        _normalise_text_token(tok, lstrip=i == 0, rstrip=i == last)
        if isinstance(tok, Text)
        else tok
        for i, tok in enumerate(inlines)
    ]


def normalise_whitespace(doc: Document) -> Document:
    """Collapse internal whitespace runs in ``Text`` tokens; trim leading/trailing on paragraphs.

    Identity-anchored paragraphs (Confluence's ``<p local-id="…">``) are
    skipped so a single-space anchor round-trips byte-for-byte.
    """
    return transform_text_blocks(doc, _normalise_inlines_ws, skip_identity_paragraphs=True)


_IDENTITY_KEYS: frozenset[str] = frozenset({"ac:local-id", "ac:macro-id", "local-id"})


def _paragraph_is_empty(block: Block) -> bool:
    if not isinstance(block, Paragraph):
        return False
    # Paragraphs with identity keys (e.g. Confluence's `local-id`) are
    # meaningful positional anchors in the source and must survive
    # normalisation, even when empty. The writer's D3 self-closing form
    # emits them as `<p />`.
    if any(k in _IDENTITY_KEYS for k in block.attributes):
        return False
    inlines = block.inlines
    if not inlines:
        return True
    if len(inlines) == 1 and isinstance(inlines[0], Text):
        content = inlines[0].content
        if content in ("", " "):
            return True
    return False


def drop_empty_paragraphs(doc: Document) -> Document:
    """Remove empty ``Paragraph`` nodes. Skipped in preserving mode."""
    return filter_blocks(doc, lambda b: not _paragraph_is_empty(b))
