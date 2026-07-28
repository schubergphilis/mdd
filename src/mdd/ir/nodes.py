"""Typed IR nodes — block + inline tiers.

Two-tier shape: `Block` nodes form the document tree; `Inline`
tokens are the leaves inside every text-bearing block. All nodes
are frozen dataclasses so that `from_json(to_json(ir)) == ir` is a
real invariant.

See [spec S28](../../../docs/spec/S28-document-ir-foundation.md)
section "Node model" for the canonical list and rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Origin metadata (spec S31 §"Whitespace preservation model")
# ---------------------------------------------------------------------------

#: Maximum ``Origin.raw_bytes`` payload retained per node, in bytes.
#:
#: Above this threshold the reader drops ``raw_bytes`` and sets
#: ``raw_bytes_truncated = True``; writers then fall back to canonical
#: rendering for that node instead of trying to splat the truncated bytes
#: back. Spec [S31](../../../docs/spec/S31-ir-normalization-and-whitespace.md)
#: §"Open questions" #1 (decided 2026-05-13: 256 KiB).
ORIGIN_RAW_BYTES_CAP: int = 256 * 1024


@dataclass(frozen=True)
class Origin:
    """Lossless source-form metadata. Optional — only populated in preserving mode.

    ``raw_bytes`` captures the verbatim source byte slice for ``Text`` leaves
    and ``RawBlock`` / ``RawInline`` nodes. For structural nodes it is ``b""``
    and only ``leading_ws`` / ``trailing_ws`` / ``entity_form`` are set.

    ``entity_form`` maps the codepoint offset within the decoded ``Text.content``
    to the original entity string (e.g. ``{3: "&hellip;"}``) so the Confluence
    writer can re-substitute the entity at the right position.

    When ``raw_bytes`` would exceed :data:`ORIGIN_RAW_BYTES_CAP`, it is dropped
    and ``raw_bytes_truncated`` is set to ``True``. Writers consult that flag
    and fall back to their canonical render for the affected node, since a
    partial slice cannot be re-emitted faithfully.
    """

    source_format: Literal["confluence-storage", "markdown", "html"]
    raw_bytes: bytes = b""
    leading_ws: str = ""
    trailing_ws: str = ""
    entity_form: dict[int, str] = field(default_factory=dict)
    raw_bytes_truncated: bool = False

    def __post_init__(self) -> None:
        # Enforce the per-node raw_bytes cap. Frozen dataclass → use
        # object.__setattr__ to mutate during __post_init__.
        if len(self.raw_bytes) > ORIGIN_RAW_BYTES_CAP:
            object.__setattr__(self, "raw_bytes", b"")
            object.__setattr__(self, "raw_bytes_truncated", True)


# ---------------------------------------------------------------------------
# Inline tokens
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Text:
    content: str
    origin: Origin | None = None


@dataclass(frozen=True)
class LineBreak:
    pass


@dataclass(frozen=True)
class SoftBreak:
    pass


@dataclass(frozen=True)
class Strong:
    tokens: list[Inline] = field(default_factory=list)


@dataclass(frozen=True)
class Emph:
    tokens: list[Inline] = field(default_factory=list)


@dataclass(frozen=True)
class Strikethrough:
    tokens: list[Inline] = field(default_factory=list)


@dataclass(frozen=True)
class Code:
    content: str
    origin: Origin | None = None


@dataclass(frozen=True)
class Link:
    href: str
    tokens: list[Inline] = field(default_factory=list)
    title: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    origin: Origin | None = None


@dataclass(frozen=True)
class ConfluenceLink:
    """`<ac:link><ri:* />` family.

    ``block_level`` is set by the storage reader when the link appeared as a
    direct child of a block container (no ``<p>`` wrapper). The storage writer
    consults it to emit the link bare on the round-trip — without it the
    writer would re-wrap the link in a synthetic ``<p>``.

    Typed child-element fields (``space_key``, ``version_at_save``, etc.) are
    populated by the storage reader from ``<ri:*>`` child elements.
    ``attributes`` carries all source-order ``<ac:link>`` attributes.
    """

    target_kind: Literal["page", "attachment", "blogpost", "url", "anchor", "user", "shortcut"]
    target: str
    body_tokens: list[Inline] = field(default_factory=list)
    block_level: bool = False
    # Typed child-element fields (populated by storage reader):
    space_key: str = ""
    version_at_save: str = ""
    posting_day: str = ""
    page_title: str = ""
    page_space_key: str = ""
    user_local_id: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    origin: Origin | None = None


@dataclass(frozen=True)
class Image:
    src: str
    alt: str = ""
    title: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    origin: Origin | None = None


@dataclass(frozen=True)
class ConfluenceImage:
    """`<ac:image>` with `<ri:attachment>` or `<ri:url>` child.

    ``block_level`` mirrors the same field on :class:`ConfluenceLink` — set
    by the storage reader when the image appeared as a direct child of a
    block container, consulted by the storage writer to skip the ``<p>``
    wrapper on the round-trip.

    ``attachment_version`` holds ``ri:version-at-save`` from the
    ``<ri:attachment>`` child element.

    ``attributes`` carries all source-order ``<ac:image>`` attributes
    (width, height, align, alt, local-id, etc.) with ``ac:``-prefixed keys.
    """

    source_kind: Literal["attachment", "url"]
    source: str
    block_level: bool = False
    attachment_version: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    origin: Origin | None = None


@dataclass(frozen=True)
class InlineMacro:
    """`<ac:structured-macro>` used inline (status, mention, …)."""

    name: str
    params: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)
    origin: Origin | None = None


@dataclass(frozen=True)
class Emoticon:
    """`<ac:emoticon>` element."""

    name: str


@dataclass(frozen=True)
class Placeholder:
    """`<ac:placeholder>` element."""

    content: str


@dataclass(frozen=True)
class RawInline:
    """Opaque inline fallback. See `fallback.py` for the contract."""

    content: str
    format: str = "xhtml"
    origin: Origin | None = None


Inline = (
    Text
    | LineBreak
    | SoftBreak
    | Strong
    | Emph
    | Strikethrough
    | Code
    | Link
    | ConfluenceLink
    | Image
    | ConfluenceImage
    | InlineMacro
    | Emoticon
    | Placeholder
    | RawInline
)


# ---------------------------------------------------------------------------
# Block nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HorizontalRule:
    node_id: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


@dataclass(frozen=True)
class Heading:
    level: int
    inlines: list[Inline] = field(default_factory=list)
    node_id: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


@dataclass(frozen=True)
class Paragraph:
    inlines: list[Inline] = field(default_factory=list)
    node_id: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


@dataclass(frozen=True)
class ListItem:
    children: list[Block] = field(default_factory=list)
    node_id: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


@dataclass(frozen=True)
class BulletList:
    items: list[ListItem] = field(default_factory=list)
    tight: bool = False
    node_id: str = ""
    compact: bool = False
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


@dataclass(frozen=True)
class OrderedList:
    items: list[ListItem] = field(default_factory=list)
    start: int = 1
    tight: bool = False
    node_id: str = ""
    compact: bool = False
    omit_start: bool = False
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


@dataclass(frozen=True)
class CodeBlock:
    content: str
    language: str | None = None
    info: str | None = None
    node_id: str = ""
    no_wrapper: bool = False
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


@dataclass(frozen=True)
class BlockQuote:
    children: list[Block] = field(default_factory=list)
    node_id: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


@dataclass(frozen=True)
class TableCell:
    children: list[Block] = field(default_factory=list)
    header: bool = False
    rowspan: int = 1
    colspan: int = 1
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TableRow:
    cells: list[TableCell] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Table:
    rows: list[TableRow] = field(default_factory=list)
    has_header: bool = False
    align: list[Literal["default", "left", "right", "center"]] = field(default_factory=list)
    node_id: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


@dataclass(frozen=True)
class Callout:
    kind: Literal["tip", "info", "note", "warning", "panel"]
    body: list[Block] = field(default_factory=list)
    title: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    node_id: str = ""
    body_leading_ws: str = ""
    body_trailing_ws: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


@dataclass(frozen=True)
class ConfluenceMacro:
    """`<ac:structured-macro>` other than the callout family or `code`."""

    name: str
    params: dict[str, str] = field(default_factory=dict)
    body: list[Block] = field(default_factory=list)
    plain_body: str | None = None
    rich_body: bool = False
    node_id: str = ""
    body_leading_ws: str = ""
    body_trailing_ws: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


@dataclass(frozen=True)
class LayoutCell:
    children: list[Block] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LayoutSection:
    layout_type: str
    cells: list[LayoutCell] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Layout:
    sections: list[LayoutSection] = field(default_factory=list)
    node_id: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


@dataclass(frozen=True)
class RawBlock:
    """Opaque block fallback. See `fallback.py` for the contract."""

    content: str
    format: str = "xhtml"
    node_id: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    trailing_ws: str | None = None
    origin: Origin | None = None


Block = (
    HorizontalRule
    | Heading
    | Paragraph
    | BulletList
    | OrderedList
    | CodeBlock
    | BlockQuote
    | Table
    | Callout
    | ConfluenceMacro
    | Layout
    | RawBlock
)


# Class-name → class lookup, for the JSON deserializer in serialize.py.
_BLOCK_CLASSES: dict[str, type] = {
    "HorizontalRule": HorizontalRule,
    "Heading": Heading,
    "Paragraph": Paragraph,
    "ListItem": ListItem,
    "BulletList": BulletList,
    "OrderedList": OrderedList,
    "CodeBlock": CodeBlock,
    "BlockQuote": BlockQuote,
    "TableCell": TableCell,
    "TableRow": TableRow,
    "Table": Table,
    "Callout": Callout,
    "ConfluenceMacro": ConfluenceMacro,
    "Layout": Layout,
    "LayoutSection": LayoutSection,
    "LayoutCell": LayoutCell,
    "RawBlock": RawBlock,
}

_INLINE_CLASSES: dict[str, type] = {
    "Text": Text,
    "LineBreak": LineBreak,
    "SoftBreak": SoftBreak,
    "Strong": Strong,
    "Emph": Emph,
    "Strikethrough": Strikethrough,
    "Code": Code,
    "Link": Link,
    "ConfluenceLink": ConfluenceLink,
    "Image": Image,
    "ConfluenceImage": ConfluenceImage,
    "InlineMacro": InlineMacro,
    "Emoticon": Emoticon,
    "Placeholder": Placeholder,
    "RawInline": RawInline,
}

ALL_CLASSES: dict[str, type] = {**_BLOCK_CLASSES, **_INLINE_CLASSES, "Origin": Origin}
