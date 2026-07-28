"""Code-block rendering: ``<ac:structured-macro ac:name="code">`` and ``<pre>``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from xml.sax.saxutils import escape

from ..cdata import wrap as cdata_wrap
from .entities import emit_attrs, render_preserved_text

if TYPE_CHECKING:
    from mdd.ir.nodes import CodeBlock


def render_code_block(
    block: CodeBlock,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> None:
    if block.attributes.get("ac:macro-id") or block.attributes.get("ac:local-id"):
        # Render as `<ac:structured-macro ac:name="code" …>`. `attributes`
        # has all source-order attrs (ac:name, ac:schema-version, ac:macro-id,
        # ac:local-id) since the macros.py reader now includes them.
        out.append(f"<ac:structured-macro{emit_attrs(block.attributes)}>")
        if block.language:
            out.append(f'<ac:parameter ac:name="language">{escape(block.language)}</ac:parameter>')
        out.append(f"<ac:plain-text-body>{cdata_wrap(block.content)}</ac:plain-text-body>")
        out.append("</ac:structured-macro>")
        return
    if block.no_wrapper:
        out.append(f"<pre{emit_attrs(block.attributes)}>")
    else:
        class_attr = f' class="language-{escape(block.language)}"' if block.language else ""
        out.append(f"<pre{emit_attrs(block.attributes)}><code{class_attr}>")
    # Honour `entity_form` whenever it's present (same policy as Text/Code
    # inlines after D5). lxml decodes `&quot;` → `"` etc. during parse, but
    # re-emitting `"` instead of `&quot;` tanks the M1 ratio even though
    # the storage is semantically identical.
    if block.origin is not None and block.origin.entity_form:
        render_preserved_text(block.content, block.origin.entity_form, out)
    else:
        out.append(escape(block.content))
    if block.no_wrapper:
        out.append("</pre>")
    else:
        out.append("</code></pre>")
