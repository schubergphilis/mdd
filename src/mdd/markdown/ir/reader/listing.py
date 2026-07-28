"""List-item consumption: ``bullet_list_open`` / ``ordered_list_open`` runs."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from mdd.ir.nodes import Block, ListItem, Paragraph, RawInline, Text

if TYPE_CHECKING:
    from markdown_it.token import Token

    from mdd.ir.fallback import IRContext

# Checkbox patterns injected by the tasklists plugin.
_CHECKED_RE = re.compile(r'checked="checked"', re.IGNORECASE)


def consume_list(tokens: list[Token], i: int, ctx: IRContext | None) -> tuple[list[ListItem], int]:
    # Deferred import (PLC0415) to break the listing <-> blocks cycle.
    from .blocks import consume_block  # noqa: PLC0415

    items: list[ListItem] = []
    open_type = tokens[i].type
    close_type = open_type.replace("_open", "_close")
    i += 1
    while i < len(tokens) and tokens[i].type != close_type:
        if tokens[i].type == "list_item_open":
            item_tok = tokens[i]
            children: list[Block] = []
            i += 1
            while i < len(tokens) and tokens[i].type != "list_item_close":
                i = consume_block(tokens, i, children, ctx)
            i += 1
            item_attrs = _detect_task_item(item_tok, children)
            if item_attrs:
                children = _strip_checkbox_from_children(children)
            items.append(ListItem(children=children, attributes=item_attrs))
        else:
            i += 1
    return items, i + 1


def _detect_task_item(item_tok: Token, children: list[Block]) -> dict[str, str]:
    """Return ``{"task": "done"|"open"}`` if the list item is a task item."""
    if item_tok.attrGet("class") != "task-list-item":
        return {}
    # Look for the injected html_inline checkbox in the first paragraph.
    if not children:
        return {}
    first = children[0]
    if not isinstance(first, Paragraph):
        return {}
    for inline in first.inlines:
        if isinstance(inline, RawInline) and 'type="checkbox"' in inline.content:
            if _CHECKED_RE.search(inline.content):
                return {"task": "done"}
            return {"task": "open"}
    return {}


def _strip_checkbox_from_children(children: list[Block]) -> list[Block]:
    """Remove the injected checkbox RawInline from the first paragraph."""
    if not children:
        return children
    first = children[0]
    if not isinstance(first, Paragraph):
        return children
    new_inlines = [
        t
        for t in first.inlines
        if not (isinstance(t, RawInline) and 'type="checkbox"' in t.content)
    ]
    # Strip the leading space that the tasklists plugin leaves.
    if new_inlines and isinstance(new_inlines[0], Text):
        new_inlines[0] = Text(new_inlines[0].content.lstrip(" "))
    new_first = replace(first, inlines=new_inlines)
    return [new_first, *children[1:]]
