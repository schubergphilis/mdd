"""Document container and identity-walk helpers.

`Document` is the root of the IR. It carries the top-level block
list plus the metadata fields called out in
[spec S28](../../../docs/spec/S28-document-ir-foundation.md)
section "Public API": `source_format`, `parsed_at`, `fallbacks`,
plus `page_title` and `node_id_counter`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from .nodes import (
    Block,
    BlockQuote,
    BulletList,
    Callout,
    ConfluenceMacro,
    Heading,
    Inline,
    Layout,
    OrderedList,
    Paragraph,
    Table,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .errors import FallbackEmitted


@dataclass(frozen=True)
class Document:
    """Root of the IR.

    `children` holds the top-level blocks. Metadata fields are
    optional and default to empty so callers that don't care about
    provenance can stay terse.
    """

    children: list[Block] = field(default_factory=list)
    page_title: str | None = None
    node_id_counter: int = 0
    source_format: str = ""
    parsed_at: str = ""
    fallbacks: list[FallbackEmitted] = field(default_factory=list)

    def iter_blocks(self) -> list[Block]:
        """Top-level blocks in document order."""
        return list(self.children)

    def iter_identity_ids(self) -> list[str]:
        """Every `ac:macro-id` / `ac:local-id` reachable in the tree."""
        out: list[str] = []
        _collect_identity(self.children, out)
        return out


def _collect_node_identity(node: object, out: list[str]) -> None:
    """Append ac:macro-id / ac:local-id values from one node to *out*."""
    source = getattr(node, "attributes", None)
    if source:
        for key in ("ac:macro-id", "ac:local-id"):
            value = source.get(key)
            if value:
                out.append(value)


def _typed_identity_children(node: object) -> Iterable[Sequence[Block | Inline]]:
    """Yield typed-container child lists for the identity walk.

    The set of identity-bearing block containers is closed; each kind names
    the field its descendants live on. Splitting per-row table walking and
    per-section layout walking into helpers keeps this dispatch flat.
    """
    if isinstance(node, (BulletList, OrderedList)):
        for item in node.items:
            yield item.children
        return
    if isinstance(node, BlockQuote):
        yield node.children
        return
    if isinstance(node, (Callout, ConfluenceMacro)):
        yield node.body
        return
    if isinstance(node, Table):
        yield from _table_identity_children(node)
        return
    if isinstance(node, Layout):
        yield from _layout_identity_children(node)
        return
    if isinstance(node, (Heading, Paragraph)):
        yield cast("Sequence[Block | Inline]", node.inlines)


def _table_identity_children(node: Table) -> Iterable[Sequence[Block | Inline]]:
    for row in node.rows:
        # Row itself participates in identity collection so per-row attrs
        # (e.g. ac:local-id on `<tr>`) are picked up.
        yield cast("Sequence[Block | Inline]", [row])
        for cell in row.cells:
            yield cell.children


def _layout_identity_children(node: Layout) -> Iterable[Sequence[Block | Inline]]:
    for section in node.sections:
        for cell in section.cells:
            yield cell.children


def _duck_identity_children(node: object) -> Iterable[Sequence[Block | Inline]]:
    """Yield `tokens` / `body_tokens` lists shared by several inline node kinds.

    Looked up by attribute rather than type because the same shape recurs
    across multiple inline classes (Strong/Emph/Link/ConfluenceLink/Code/...).
    """
    for attr in ("tokens", "body_tokens"):
        value = getattr(node, attr, None)
        if isinstance(value, list):
            yield cast("Sequence[Block | Inline]", value)


def _collect_identity(nodes: list[Block] | list[Inline], out: list[str]) -> None:
    for node in nodes:
        _collect_node_identity(node, out)
        for child_list in _typed_identity_children(node):
            _collect_identity(cast("list[Block]", list(child_list)), out)
        for child_list in _duck_identity_children(node):
            _collect_identity(cast("list[Block]", list(child_list)), out)
