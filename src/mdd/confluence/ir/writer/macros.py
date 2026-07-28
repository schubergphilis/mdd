"""Confluence storage macro renderers: ``<ac:image>`` and inline structured macros."""

from __future__ import annotations

from typing import TYPE_CHECKING
from xml.sax.saxutils import quoteattr

from .entities import emit_attrs

if TYPE_CHECKING:
    from mdd.ir.nodes import ConfluenceImage, InlineMacro


def render_confluence_image(tok: ConfluenceImage, out: list[str]) -> None:
    # `attributes` has all source-order `<ac:image>` attrs (ac:width,
    # ac:height, ac:local-id, …) when the node came from storage or was
    # reattached. For markdown-sourced images, attributes carries ac:-prefixed
    # presentation keys from the URI extras (e.g. ac:width, ac:alt).
    # Emit only non-source-child attributes on the <ac:image> element.
    _SOURCE_CHILD_ATTRS = frozenset({"ac:version-at-save"})
    img_attr_dict = {k: v for k, v in tok.attributes.items() if k not in _SOURCE_CHILD_ATTRS}
    out.append(f"<ac:image{emit_attrs(img_attr_dict)}>")
    if tok.source_kind == "attachment":
        att_attrs = f" ri:filename={quoteattr(tok.source)}"
        if tok.attachment_version:
            att_attrs += f" ri:version-at-save={quoteattr(tok.attachment_version)}"
        out.append(f"<ri:attachment{att_attrs} />")
    else:
        out.append(f"<ri:url ri:value={quoteattr(tok.source)} />")
    out.append("</ac:image>")


def render_inline_macro(tok: InlineMacro, out: list[str]) -> None:
    # `attributes` has all source-order attrs (ac:name, ac:schema-version,
    # ac:local-id, ac:macro-id) when the node came from storage or was
    # reattached. For markdown-sourced inline macros (attributes empty),
    # emit ac:name from the typed `name` field.
    if "ac:name" not in tok.attributes:
        attrs_str = f" ac:name={quoteattr(tok.name)}"
    else:
        attrs_str = emit_attrs(tok.attributes)
    out.append(f"<ac:structured-macro{attrs_str}>")
    for key, value in tok.params.items():
        # Param values may contain raw markup (e.g. `<ri:attachment …/>`
        # inside a `view-file` macro, fixture 164069). The reader stores
        # parameter content verbatim via `etree.tostring`, so emit it raw
        # — same convention as the block-level `ConfluenceMacro` writer.
        out.append(f"<ac:parameter ac:name={quoteattr(key)}>{value}</ac:parameter>")
    out.append("</ac:structured-macro>")
