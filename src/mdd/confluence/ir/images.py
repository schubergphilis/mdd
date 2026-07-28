"""``<ac:image>`` → ``ConfluenceImage`` handler."""

from __future__ import annotations

from typing import Any

from mdd.ir.nodes import ConfluenceImage

from .attrs import all_attrs_ordered

_RI = "http://atlassian.com/repository/confluence/1.0"
_RI_ATTACHMENT = f"{{{_RI}}}attachment"
_RI_URL = f"{{{_RI}}}url"


def _read_image_source(node: Any) -> tuple[str, str, str | None]:
    """Return ``(source_kind, source, attachment_version)`` for the first
    ``<ri:attachment>`` or ``<ri:url>`` child.
    Defaults to ``("url", "", None)`` when no recognised child is present.
    """
    for child in node:
        tag = child.tag if isinstance(child.tag, str) else ""
        if tag == _RI_ATTACHMENT:
            filename = child.get(f"{{{_RI}}}filename") or ""
            version = child.get(f"{{{_RI}}}version-at-save") or None
            return "attachment", filename, version
        if tag == _RI_URL:
            url = child.get(f"{{{_RI}}}value") or ""
            return "url", url, None
    return "url", "", None


def read_ac_image(node: Any) -> ConfluenceImage:
    """Parse an ``<ac:image>`` element into a ``ConfluenceImage`` node."""
    source_kind, source, attachment_version = _read_image_source(node)
    return ConfluenceImage(
        source_kind=source_kind,  # type: ignore[arg-type]
        source=source,
        attachment_version=attachment_version,
        attributes=all_attrs_ordered(node),
    )
