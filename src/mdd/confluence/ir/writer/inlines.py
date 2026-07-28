"""Inline-level IR → Confluence storage rendering and dispatch."""

from __future__ import annotations

from typing import Literal, cast
from xml.sax.saxutils import escape, quoteattr

from mdd.ir.nodes import (
    Code,
    ConfluenceImage,
    ConfluenceLink,
    Emoticon,
    Emph,
    Image,
    Inline,
    InlineMacro,
    LineBreak,
    Link,
    Placeholder,
    SoftBreak,
    Strikethrough,
    Strong,
    Text,
)

from .entities import emit_attrs, render_preserved_text, render_text_preserving
from .links import render_confluence_link
from .macros import render_confluence_image, render_inline_macro


def render_inlines(
    tokens: list[Inline],
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    for tok in tokens:
        render_inline(tok, out, mode=mode)


def _render_text(
    tok: Text,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    # Re-emit captured HTML entities even in normalising mode when the
    # Origin carries them. lxml decodes `&mdash;` → `—`, `&hellip;` → `…`
    # etc. during parse, but emitting the Unicode codepoint back drops
    # the M1 SequenceMatcher ratio below the 0.995 (R1) / 0.95 (R3)
    # gates even though the storage is semantically identical. Honour
    # `entity_form` whenever it's present — there is no "normalising
    # canonical form" that says `&mdash;` is wrong, it's a stylistic
    # round-trip preference of the source. Fresh IR with no Origin
    # still emits canonical XML escaping via the `else` branch.
    if tok.origin is not None and tok.origin.entity_form:
        render_preserved_text(tok.content, tok.origin.entity_form, out)
    elif mode == "preserving":
        render_text_preserving(tok, out)
    else:
        out.append(escape(tok.content))


def _render_linebreak(
    tok: LineBreak,  # noqa: ARG001
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> None:
    out.append("<br />")


def _render_softbreak(
    tok: SoftBreak,  # noqa: ARG001
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> None:
    out.append("\n")


def _render_wrapped_inline(
    open_tag: str, close_tag: str, tokens: list[Inline], out: list[str], mode: str
) -> None:
    out.append(open_tag)
    render_inlines(tokens, out, mode=cast("Literal['normalising', 'preserving']", mode))
    out.append(close_tag)


def _render_strong(
    tok: Strong,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    _render_wrapped_inline("<strong>", "</strong>", tok.tokens, out, mode)


def _render_emph(
    tok: Emph,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    _render_wrapped_inline("<em>", "</em>", tok.tokens, out, mode)


def _render_strikethrough(
    tok: Strikethrough,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    _render_wrapped_inline("<s>", "</s>", tok.tokens, out, mode)


def _render_code(
    tok: Code,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> None:
    out.append("<code>")
    # Same entity_form re-emission policy as Text (see above): honour
    # `entity_form` in either mode.
    if tok.origin is not None and tok.origin.entity_form:
        render_preserved_text(tok.content, tok.origin.entity_form, out)
    else:
        out.append(escape(tok.content))
    out.append("</code>")


def _render_link(
    tok: Link,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    attrs = f" href={quoteattr(tok.href)}" + emit_attrs(tok.attributes)
    out.append(f"<a{attrs}>")
    render_inlines(tok.tokens, out, mode=mode)
    out.append("</a>")


def _render_image(
    tok: Image,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> None:
    attrs = f" src={quoteattr(tok.src)}"
    if tok.alt:
        attrs += f" alt={quoteattr(tok.alt)}"
    attrs += emit_attrs(tok.attributes)
    out.append(f"<img{attrs} />")


def _render_emoticon(
    tok: Emoticon,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> None:
    # Canonical Confluence form has a space before `/>` — matches the
    # storage shape every other self-closing element in this writer
    # already emits (`<br />`, `<img … />`, `<ri:page … />`, …) and the
    # form Confluence's own renderer produces.
    out.append(f"<ac:emoticon ac:name={quoteattr(tok.name)} />")


def _render_placeholder(
    tok: Placeholder,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> None:
    out.append("<ac:placeholder>")
    out.append(escape(tok.content))
    out.append("</ac:placeholder>")


def _render_confluence_image_inline(
    tok: ConfluenceImage,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> None:
    render_confluence_image(tok, out)


def _render_inline_macro_inline(
    tok: InlineMacro,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> None:
    render_inline_macro(tok, out)


_INLINE_RENDERERS: dict[type, object] = {
    Text: _render_text,
    LineBreak: _render_linebreak,
    SoftBreak: _render_softbreak,
    Strong: _render_strong,
    Emph: _render_emph,
    Strikethrough: _render_strikethrough,
    Code: _render_code,
    Link: _render_link,
    Image: _render_image,
    ConfluenceLink: render_confluence_link,
    ConfluenceImage: _render_confluence_image_inline,
    InlineMacro: _render_inline_macro_inline,
    Emoticon: _render_emoticon,
    Placeholder: _render_placeholder,
}


def render_inline(
    tok: Inline,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    renderer = _INLINE_RENDERERS.get(type(tok))
    if renderer is None:
        out.append(tok.content)  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType,reportUnknownArgumentType]
        return
    renderer(tok, out, mode=mode)  # pyright: ignore[reportCallIssue]
