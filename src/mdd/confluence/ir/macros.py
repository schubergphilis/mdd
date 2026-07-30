"""``<ac:structured-macro>`` → ``Callout`` / ``CodeBlock`` / ``ConfluenceMacro`` promotion.

Handles the macro-body parsing, parameter extraction, and structured-macro
dispatch.  Also handles inline macros (``InlineMacro``).
"""

from __future__ import annotations

import re
from typing import Any

from lxml import etree

from mdd.ir.nodes import Block, Callout, CodeBlock, ConfluenceMacro, Inline, InlineMacro, RawInline

from .attrs import all_attrs_ordered
from .fallback import serialize_raw

# lxml's `etree.tostring` always emits xmlns declarations for namespaced
# elements (because the element is serialised in isolation). Strip them
# so `<ri:attachment …/>` inside `<ac:parameter>` round-trips to the
# original storage shape — the surrounding document already binds `ri:`
# and `ac:` so the declarations are redundant. Also re-add the canonical
# space before `/>` to match Confluence's self-closing form.
_NS_DECL_RE = re.compile(r' xmlns:(?:ri|ac)="[^"]*"')


def _clean_serialised_child(serialised: str) -> str:
    """Strip redundant xmlns declarations and normalise self-closing space."""
    cleaned = _NS_DECL_RE.sub("", serialised)
    return re.sub(r"(?<! )/>", " />", cleaned)


_AC = "http://atlassian.com/content"

_AC_PARAMETER = f"{{{_AC}}}parameter"
_AC_RICH_TEXT_BODY = f"{{{_AC}}}rich-text-body"
_AC_PLAIN_TEXT_BODY = f"{{{_AC}}}plain-text-body"
_AC_NAME = f"{{{_AC}}}name"
_AC_SCHEMA_VERSION = f"{{{_AC}}}schema-version"

_CALLOUT_NAMES = frozenset({"info", "tip", "note", "warning", "panel"})


def _read_parameter_value(param_node: Any) -> str:
    """Concatenate a parameter's text and serialised child elements, with
    redundant xmlns declarations stripped (`<ri:attachment …/>` inside an
    `<ac:parameter>` already lives in a namespace-aware parent)."""
    return (param_node.text or "") + "".join(
        _clean_serialised_child(etree.tostring(g, encoding="unicode")) for g in param_node
    )


def _leading_ws_of(text: str) -> str:
    """Return the run of leading whitespace at the start of ``text``."""
    if not text:
        return ""
    if not text.strip():
        return text
    return text[: len(text) - len(text.lstrip())]


def _trailing_ws_of(text: str) -> str:
    """Return the run of trailing whitespace at the end of ``text``."""
    if not text:
        return ""
    if not text.strip():
        return text
    trailing = len(text) - len(text.rstrip())
    return text[len(text) - trailing :]


def _read_rich_body_whitespace(child: Any) -> tuple[str, str]:
    """Capture the leading whitespace inside the opening
    ``<ac:rich-text-body>`` tag and the trailing whitespace before the
    closing tag. Both round-trip the original indentation that
    ``read_blocks_from_container`` would otherwise strip."""
    leading = _leading_ws_of(child.text or "")
    grandchildren = list(child)
    if not grandchildren:
        return leading, ""
    return leading, _trailing_ws_of(grandchildren[-1].tail or "")


def read_macro_bodies(
    node: Any,
    read_blocks_fn: Any,
) -> tuple[dict[str, str], list[Block] | None, str | None, bool, str, str]:
    """Extract parameters and body from a structured-macro element.

    Returns ``(params, rich_body, plain_body, has_rich_body, body_leading_ws,
    body_trailing_ws)``.

    ``has_rich_body`` is ``True`` only when an ``<ac:rich-text-body>``
    element is actually present. The writer needs that distinction so it
    does not emit an empty ``<ac:rich-text-body>`` when there is none.

    ``body_leading_ws`` / ``body_trailing_ws`` capture the whitespace
    immediately inside the opening and closing ``<ac:rich-text-body>``
    tags. ``read_blocks_from_container`` strips pure-whitespace
    inline buffers; without this capture the indentation in fixtures
    like 1114320 and 1147246 would not round-trip.
    """
    params: dict[str, str] = {}
    rich_body: list[Block] | None = None
    plain_body: str | None = None
    has_rich_body = False
    body_leading_ws = ""
    body_trailing_ws = ""

    for child in node:
        tag = child.tag if isinstance(child.tag, str) else ""
        if tag == _AC_PARAMETER:
            params[child.get(_AC_NAME) or ""] = _read_parameter_value(child)
        elif tag == _AC_RICH_TEXT_BODY:
            has_rich_body = True
            body_leading_ws, body_trailing_ws = _read_rich_body_whitespace(child)
            rich_body = read_blocks_fn(child)
        elif tag == _AC_PLAIN_TEXT_BODY:
            plain_body = child.text or ""

    return params, rich_body, plain_body, has_rich_body, body_leading_ws, body_trailing_ws


def read_structured_macro(
    node: Any,
    read_blocks_fn: Any,
) -> list[Block]:
    """Dispatch a ``<ac:structured-macro>`` element to the appropriate IR node."""
    name = node.get(_AC_NAME) or ""
    params, rich_body, plain_body, has_rich_body, body_lead_ws, body_trail_ws = read_macro_bodies(
        node, read_blocks_fn
    )

    base_attributes = all_attrs_ordered(node)

    if name in _CALLOUT_NAMES and has_rich_body:
        title = params.pop("title", None) or None
        return [
            Callout(
                kind=name,  # type: ignore[arg-type]
                body=rich_body or [],
                title=title,
                params=params,
                body_leading_ws=body_lead_ws,
                body_trailing_ws=body_trail_ws,
                attributes=base_attributes,
            )
        ]

    if name == "code":
        language = params.get("language") or None
        return [
            CodeBlock(
                content=plain_body or "",
                language=language,
                attributes=base_attributes,
            )
        ]

    return [
        ConfluenceMacro(
            name=name,
            params=params,
            body=rich_body or [],
            plain_body=plain_body,
            rich_body=has_rich_body,
            body_leading_ws=body_lead_ws,
            body_trailing_ws=body_trail_ws,
            attributes=base_attributes,
        )
    ]


def read_inline_macro(node: Any) -> Inline:
    """Inline structured-macro: status, mention, etc.

    If a body is present, fall back to a raw passthrough rather than
    lossily flattening it.
    """
    name = node.get(_AC_NAME) or ""
    params: dict[str, str] = {}
    has_body = False

    for child in node:
        tag = child.tag if isinstance(child.tag, str) else ""
        if tag == _AC_PARAMETER:
            key = child.get(_AC_NAME) or ""
            params[key] = (child.text or "") + "".join(
                _clean_serialised_child(etree.tostring(g, encoding="unicode")) for g in child
            )
        elif tag in {_AC_RICH_TEXT_BODY, _AC_PLAIN_TEXT_BODY}:
            has_body = True

    if has_body:
        return RawInline(format="confluence-storage", content=serialize_raw(node))

    return InlineMacro(
        name=name,
        params=params,
        attributes=all_attrs_ordered(node),
    )
