"""Attribute helpers for Confluence storage XHTML.

``all_attrs_ordered()`` builds the single source-order ``attributes`` dict
used by every IR node.
"""

from __future__ import annotations

from typing import Any

_AC = "http://atlassian.com/content"
_RI = "http://atlassian.com/repository/confluence/1.0"


def qname(key: str) -> str:
    """Map an lxml ``{nsuri}localname`` back to the storage prefix form."""
    if not key.startswith("{"):
        return key
    ns, _, local = key[1:].partition("}")
    if ns == _AC:
        return f"ac:{local}"
    if ns == _RI:
        return f"ri:{local}"
    return local


def all_attrs_ordered(node: Any, *, skip: tuple[str, ...] = ()) -> dict[str, str]:
    """All attributes in source order as a single dict with qname-normalised keys.

    This is the ``attributes`` dict that replaces the identity/attrs split.
    lxml preserves source attribute order via ``etree.attrib.items()``, so
    the returned dict
    round-trips byte-perfect.
    """
    skip_set = set(skip)
    return {qname(k): v for k, v in node.attrib.items() if k not in skip_set}
