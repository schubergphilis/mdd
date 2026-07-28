"""RawBlock / RawInline emission for unrecognised Confluence storage shapes.

Wires into ``mdd.ir.fallback.emit_block_fallback`` /
``emit_inline_fallback`` so every fallback lands on the ``IRContext``
and surfaces in ``document.fallbacks``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from lxml import etree

from mdd.ir.fallback import IRContext, emit_block_fallback, emit_inline_fallback

if TYPE_CHECKING:
    from mdd.ir.nodes import RawBlock, RawInline

_NS_DECL_RE = re.compile(r'\s+xmlns:(ac|ri)="[^"]+"')


def serialize_raw(node: Any) -> str:
    """Serialize an lxml element verbatim, stripping synthetic xmlns:ac/ri declarations.

    Confluence storage carries those declarations implicitly via the surrounding
    fragment context, not on every element.  Leaving them in inflates round-trip
    diffs and trips the structural-fidelity metric.
    """
    text = etree.tostring(node, encoding="unicode", with_tail=False)
    return _NS_DECL_RE.sub("", text)


def block_fallback(
    node: Any,
    *,
    ctx: IRContext | None = None,
    reason: str = "unrecognised block element",
) -> RawBlock:
    """Emit a ``RawBlock`` for an unknown block-level Confluence element."""
    content = serialize_raw(node)
    return emit_block_fallback(
        content,
        source_format="confluence-storage",
        reason=reason,
        ctx=ctx,
    )


def inline_fallback(
    node: Any,
    *,
    ctx: IRContext | None = None,
    reason: str = "unrecognised inline element",
) -> RawInline:
    """Emit a ``RawInline`` for an unknown inline Confluence element."""
    content = serialize_raw(node)
    return emit_inline_fallback(
        content,
        source_format="confluence-storage",
        reason=reason,
        ctx=ctx,
    )
