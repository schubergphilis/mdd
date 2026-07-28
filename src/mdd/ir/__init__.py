"""Document intermediate representation (IR).

Public API per
[spec S28](../../../docs/spec/S28-document-ir-foundation.md)
section "Public API". `parse_*` / `render_*` live in
`mdd.confluence.ir` and `mdd.markdown.ir` (specs 029 and 030).
"""

from __future__ import annotations

from .document import Document
from .errors import FallbackEmitted, IRError, ValidationError
from .fallback import IRContext, emit_block_fallback, emit_inline_fallback
from .identity import IdAllocator, assign_ids, reattach
from .nodes import (
    ALL_CLASSES,
    Block,
    BlockQuote,
    BulletList,
    Callout,
    Code,
    CodeBlock,
    ConfluenceImage,
    ConfluenceLink,
    ConfluenceMacro,
    Emoticon,
    Emph,
    Heading,
    HorizontalRule,
    Image,
    Inline,
    InlineMacro,
    Layout,
    LayoutCell,
    LayoutSection,
    LineBreak,
    Link,
    ListItem,
    OrderedList,
    Origin,
    Paragraph,
    Placeholder,
    RawBlock,
    RawInline,
    SoftBreak,
    Strikethrough,
    Strong,
    Table,
    TableCell,
    TableRow,
    Text,
)
from .normalize import NORMALISING_PIPELINE, normalise
from .serialize import MDD_IR_VERSION, from_json, to_json

__all__ = [
    "ALL_CLASSES",
    "MDD_IR_VERSION",
    "NORMALISING_PIPELINE",
    "Block",
    "BlockQuote",
    "BulletList",
    "Callout",
    "Code",
    "CodeBlock",
    "ConfluenceImage",
    "ConfluenceLink",
    "ConfluenceMacro",
    "Document",
    "Emoticon",
    "Emph",
    "FallbackEmitted",
    "Heading",
    "HorizontalRule",
    "IRContext",
    "IRError",
    "IdAllocator",
    "Image",
    "Inline",
    "InlineMacro",
    "Layout",
    "LayoutCell",
    "LayoutSection",
    "LineBreak",
    "Link",
    "ListItem",
    "OrderedList",
    "Origin",
    "Paragraph",
    "Placeholder",
    "RawBlock",
    "RawInline",
    "SoftBreak",
    "Strikethrough",
    "Strong",
    "Table",
    "TableCell",
    "TableRow",
    "Text",
    "ValidationError",
    "assign_ids",
    "emit_block_fallback",
    "emit_inline_fallback",
    "from_json",
    "normalise",
    "reattach",
    "to_json",
]
