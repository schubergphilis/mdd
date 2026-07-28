"""Inline-level element handlers: text, emphasis, links, images, emoticons."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mdd.ir.nodes import (
    Code,
    Emoticon,
    Emph,
    Image,
    Inline,
    LineBreak,
    Link,
    Placeholder,
    Strikethrough,
    Strong,
    Text,
)

from ..attrs import all_attrs_ordered
from ..fallback import inline_fallback
from ..images import read_ac_image
from ..links import read_ac_link
from ..macros import read_inline_macro
from ._namespaces import (
    AC,
    AC_EMOTICON,
    AC_IMAGE,
    AC_LINK,
    AC_PLACEHOLDER,
    AC_STRUCTURED_MACRO,
)

if TYPE_CHECKING:
    from mdd.ir.fallback import IRContext


def read_inline_children(node: Any, ctx: IRContext | None = None) -> list[Inline]:
    out: list[Inline] = []
    if node.text:
        out.append(Text(node.text))
    for child in node:
        out.extend(read_inline(child, ctx))
        if child.tail:
            out.append(Text(child.tail))
    return out


def _text_content(node: Any) -> str:
    return "".join(node.itertext())


def read_inline(node: Any, ctx: IRContext | None = None) -> list[Inline]:  # noqa: C901, PLR0911, PLR0912
    """Read one inline-level element."""
    tag = node.tag if isinstance(node.tag, str) else ""

    if tag in {"strong", "b"}:
        return [Strong(tokens=read_inline_children(node, ctx))]
    if tag in {"em", "i"}:
        return [Emph(tokens=read_inline_children(node, ctx))]
    if tag in {"s", "del"}:
        return [Strikethrough(tokens=read_inline_children(node, ctx))]
    if tag == "code":
        return [Code(content=_text_content(node))]
    if tag == "br":
        return [LineBreak()]
    if tag == "a":
        return [
            Link(
                href=node.get("href", ""),
                tokens=read_inline_children(node, ctx),
                attributes=all_attrs_ordered(node, skip=("href",)),
            )
        ]
    if tag == "img":
        return [
            Image(
                src=node.get("src", ""),
                alt=node.get("alt", "") or "",
                attributes=all_attrs_ordered(node, skip=("src", "alt")),
            )
        ]
    if tag in {"span", "u", "ins"}:
        return read_inline_children(node, ctx)

    if tag == AC_LINK:

        def _read_children_inline(n: Any) -> list[Inline]:
            return read_inline_children(n, ctx)

        return [read_ac_link(node, _read_children_inline, block_level=False)]
    if tag == AC_IMAGE:
        return [read_ac_image(node)]
    if tag == AC_EMOTICON:
        return [_read_emoticon(node)]
    if tag == AC_PLACEHOLDER:
        content = "".join(node.itertext())
        return [Placeholder(content=content)]
    if tag == AC_STRUCTURED_MACRO:
        return [read_inline_macro(node)]

    if not tag:
        return []

    return [inline_fallback(node, ctx=ctx, reason=f"unrecognised inline element: {tag}")]


def _read_emoticon(node: Any) -> Inline:
    name = node.get(f"{{{AC}}}name") or node.get(f"{{{AC}}}emoji-shortname") or ""
    if name:
        return Emoticon(name=name)
    return inline_fallback(node, reason="ac:emoticon without ac:name")
