"""CDATA preservation helpers for Confluence storage XHTML.

Confluence wraps code-block content in CDATA sections so special characters
pass through without escaping. The writer must reproduce that shape.
"""

from __future__ import annotations


def wrap(content: str) -> str:
    """Wrap ``content`` in a CDATA section.

    If the content itself contains ``]]>`` (CDATA end marker), split the
    section to avoid premature termination.
    """
    return "<![CDATA[" + content.replace("]]>", "]]]]><![CDATA[>") + "]]>"
