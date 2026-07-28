"""List item readers for ``<ul>``/``<ol>`` and their ``<li>`` children."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mdd.ir.nodes import Block, Inline, ListItem, Paragraph, Text

from ..attrs import all_attrs_ordered
from ._namespaces import LAYOUT_TAGS
from .inline import read_inline

if TYPE_CHECKING:
    from mdd.ir.fallback import IRContext


def read_list_items(node: Any, ctx: IRContext | None = None) -> list[ListItem]:
    out: list[ListItem] = []
    for child in node:
        if not isinstance(child.tag, str) or child.tag != "li":
            continue
        children = read_list_item_children(child, ctx)
        out.append(
            ListItem(
                children=children,
                attributes=all_attrs_ordered(child),
            )
        )
    return out


# Block-level child tags that, inside a `<li>`, terminate the running
# inline run and become sibling blocks rather than getting flattened into
# the synthetic paragraph.
_LI_BLOCK_TAGS = frozenset({"ul", "ol", "p", "blockquote", "pre", "table"})


def _is_li_block_child(tag: str) -> bool:
    return tag in _LI_BLOCK_TAGS or tag in LAYOUT_TAGS


def read_list_item_children(li_node: Any, ctx: IRContext | None = None) -> list[Block]:
    """Read a ``<li>``'s body: inline content becomes one Paragraph; nested
    lists become ``BulletList``/``OrderedList`` siblings of that paragraph."""
    # Deferred import to break the listing.py ↔ block.py cycle.
    from .block import read_block  # noqa: PLC0415

    inline: list[Inline] = []
    blocks: list[Block] = []

    if li_node.text:
        inline.append(Text(li_node.text))

    def flush() -> None:
        if any(not isinstance(t, Text) or t.content.strip() for t in inline):
            blocks.append(Paragraph(inlines=list(inline)))
        inline.clear()

    for ch in li_node:
        tag = ch.tag if isinstance(ch.tag, str) else ""
        if _is_li_block_child(tag):
            flush()
            blocks.extend(read_block(ch, ctx))
        else:
            inline.extend(read_inline(ch, ctx))
        if ch.tail:
            inline.append(Text(ch.tail))

    flush()
    return blocks
