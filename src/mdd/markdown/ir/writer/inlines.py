"""Inline-token rendering for the IR → markdown writer."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

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
    RawInline,
    SoftBreak,
    Strikethrough,
    Strong,
    Text,
)

from ..confluence_uris import render_confluence_uri
from .escape import escape_attr, escape_text, escape_url, is_safe_autolink, render_attr_dict


def render_inlines(
    tokens: list[Inline],
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    for tok in tokens:
        render_inline(tok, out, mode=mode)


_Mode = Literal["normalising", "preserving"]


def _origin_raw_bytes_for(tok: Text | RawInline, mode: _Mode) -> str | None:
    """Return the verbatim raw_bytes-decoded text for *tok* in preserving mode.

    Returns ``None`` if no origin override applies and the caller should fall
    back to the normalising path. Both ``Text`` and ``RawInline`` use the same
    rule (preserve verbatim when origin is intact); centralising it removes a
    duplicated 4-line guard.
    """
    if mode != "preserving" or tok.origin is None:
        return None
    origin = tok.origin
    if not origin.raw_bytes or origin.raw_bytes_truncated:
        return None
    return origin.raw_bytes.decode("utf-8")


def _render_text(tok: Inline, out: list[str], mode: _Mode) -> None:
    assert isinstance(tok, Text)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    raw = _origin_raw_bytes_for(tok, mode)
    out.append(raw if raw is not None else escape_text(tok.content))


def _render_raw_inline(tok: Inline, out: list[str], mode: _Mode) -> None:
    assert isinstance(tok, RawInline)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    raw = _origin_raw_bytes_for(tok, mode)
    out.append(raw if raw is not None else tok.content)


def _render_line_break(tok: Inline, out: list[str], mode: _Mode) -> None:
    del tok, mode
    out.append("  \n")


def _render_soft_break(tok: Inline, out: list[str], mode: _Mode) -> None:
    del tok, mode
    out.append(" ")


def _render_strong(tok: Inline, out: list[str], mode: _Mode) -> None:
    assert isinstance(tok, Strong)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    _render_wrapped("**", tok.tokens, out, mode)


def _render_emph(tok: Inline, out: list[str], mode: _Mode) -> None:
    assert isinstance(tok, Emph)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    _render_wrapped("*", tok.tokens, out, mode)


def _render_strikethrough(tok: Inline, out: list[str], mode: _Mode) -> None:
    assert isinstance(tok, Strikethrough)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    _render_wrapped("~~", tok.tokens, out, mode)


def _render_code(tok: Inline, out: list[str], mode: _Mode) -> None:
    del mode
    assert isinstance(tok, Code)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    n = 1
    while "`" * n in tok.content:
        n += 1
    ticks = "`" * n
    pad = " " if tok.content.startswith("`") or tok.content.endswith("`") else ""
    out.append(f"{ticks}{pad}{tok.content}{pad}{ticks}")


def _render_wrapped(delim: str, tokens: list[Inline], out: list[str], mode: _Mode) -> None:
    out.append(delim)
    render_inlines(tokens, out, mode=mode)
    out.append(delim)


def _render_link(tok: Inline, out: list[str], mode: _Mode) -> None:
    assert isinstance(tok, Link)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    body: list[str] = []
    render_inlines(tok.tokens, body, mode=mode)
    body_text = "".join(body)
    # Prefer the CommonMark autolink form `<href>` when the body text
    # equals the href and there's no title — emitting the verbose
    # `[href](href)` form would add visual noise the reader cannot
    # distinguish from the autolink shape. Storage XHTML is the same
    # ``<a href="X">X</a>`` either way.
    if not tok.title and body_text == tok.href and is_safe_autolink(tok.href):
        out.append(f"<{tok.href}>")
        return
    title_part = f' "{tok.title}"' if tok.title else ""
    out.append(f"[{body_text}]({escape_url(tok.href)}{title_part})")


def _render_image(tok: Inline, out: list[str], mode: _Mode) -> None:
    del mode
    assert isinstance(tok, Image)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    title_part = f' "{tok.title}"' if tok.title else ""
    out.append(f"![{escape_text(tok.alt)}]({escape_url(tok.src)}{title_part})")


def _render_confluence_link_dispatch(tok: Inline, out: list[str], mode: _Mode) -> None:
    assert isinstance(tok, ConfluenceLink)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    _render_confluence_link(tok, out, mode=mode)


def _render_confluence_image_dispatch(tok: Inline, out: list[str], mode: _Mode) -> None:
    del mode
    assert isinstance(tok, ConfluenceImage)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    _render_confluence_image(tok, out)


def _render_inline_macro_dispatch(tok: Inline, out: list[str], mode: _Mode) -> None:
    del mode
    assert isinstance(tok, InlineMacro)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    _render_inline_macro(tok, out)


def _render_emoticon(tok: Inline, out: list[str], mode: _Mode) -> None:
    del mode
    assert isinstance(tok, Emoticon)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    out.append(f'{{{{confluence:emoticon name="{escape_attr(tok.name)}"}}}}')


def _render_placeholder(tok: Inline, out: list[str], mode: _Mode) -> None:
    del mode
    assert isinstance(tok, Placeholder)  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    out.append(f'{{{{confluence:placeholder content="{escape_attr(tok.content)}"}}}}')


# Per-type rendering dispatch. The set of Inline subtypes is closed
# (sealed by the IR — see `mdd.ir.nodes`), so a `dict[type, Callable]`
# is the natural pairing of "predicate" (isinstance) and "action"
# (render). Adding a new Inline subtype is one new entry here.
_INLINE_RENDERERS: dict[type, Callable[[Inline, list[str], _Mode], None]] = {
    Text: _render_text,
    LineBreak: _render_line_break,
    SoftBreak: _render_soft_break,
    Strong: _render_strong,
    Emph: _render_emph,
    Strikethrough: _render_strikethrough,
    Code: _render_code,
    Link: _render_link,
    Image: _render_image,
    ConfluenceLink: _render_confluence_link_dispatch,
    ConfluenceImage: _render_confluence_image_dispatch,
    InlineMacro: _render_inline_macro_dispatch,
    Emoticon: _render_emoticon,
    Placeholder: _render_placeholder,
    RawInline: _render_raw_inline,
}


def render_inline(
    tok: Inline,
    out: list[str],
    *,
    mode: _Mode = "normalising",
) -> None:
    _INLINE_RENDERERS[type(tok)](tok, out, mode)


def _render_confluence_link(
    tok: ConfluenceLink,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    if tok.target_kind == "url":
        body: list[str] = []
        render_inlines(tok.body_tokens, body, mode=mode)
        out.append(f"[{''.join(body)}]({escape_url(tok.target)})")
        return
    uri = render_confluence_uri(tok)
    body_parts: list[str] = []
    render_inlines(tok.body_tokens, body_parts, mode=mode)
    # Emit ``[](uri)`` when ``body_tokens`` is empty so a bare
    # ``<ac:link><ri:user/></ac:link>`` (no ``<ac:link-body>``) round-trips
    # without spuriously injecting a link-body on the next render. The
    # previous fallback (``body_text or tok.target``) collapsed the bare
    # and self-titled forms onto the same markdown shape.
    body_text = "".join(body_parts)
    out.append(f"[{body_text}]({escape_url(uri)})")


def _render_confluence_image(tok: ConfluenceImage, out: list[str]) -> None:
    uri = render_confluence_uri(tok)
    # Width/height/align attrs also go in the image title slot as a secondary
    # readability hint. Only emit ac:-prefixed keys (not ac:alt) in title.
    title_attrs = {
        k[3:]: v for k, v in tok.attributes.items() if k.startswith("ac:") and k != "ac:alt"
    }
    alt = tok.attributes.get("ac:alt", "")
    if title_attrs:
        title = " ".join(f"{k}={v}" for k, v in title_attrs.items())
        out.append(f'![{escape_text(alt)}]({escape_url(uri)} "{title}")')
    else:
        out.append(f"![{escape_text(alt)}]({escape_url(uri)})")


def _render_inline_macro(tok: InlineMacro, out: list[str]) -> None:
    if any(_param_is_complex(v) for v in tok.params.values()):
        out.append(_render_inline_macro_b64(tok))
        return
    attrs = render_attr_dict(tok.params)
    if attrs:
        out.append(f"{{{{confluence:{tok.name} {attrs}}}}}")
    else:
        out.append(f"{{{{confluence:{tok.name}}}}}")


def _param_is_complex(value: str) -> bool:
    return "<" in value or "\n" in value or "}}" in value


def _render_inline_macro_b64(tok: InlineMacro) -> str:
    parts = [f'<ac:structured-macro ac:name="{tok.name}"']
    for key in ("ac:schema-version", "ac:local-id", "ac:macro-id"):
        if tok.attributes.get(key):
            parts.append(f' {key}="{tok.attributes[key]}"')  # noqa: PERF401
    parts.append(">")
    for key, value in tok.params.items():
        parts.append(f'<ac:parameter ac:name="{key}">{value}</ac:parameter>')
    parts.append("</ac:structured-macro>")
    xml = "".join(parts)
    encoded = base64.b64encode(xml.encode("utf-8")).decode("ascii")
    return f"{{{{confluence-raw:{encoded}}}}}"
