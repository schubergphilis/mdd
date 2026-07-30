"""Attachment references extracted from a parsed Confluence document.

The legacy ``storage_to_md`` converter returned an ``AttachmentRef`` list
alongside the markdown body so callers (``export.py``) could pre-download
body-referenced attachments before the ``sync_all_attachments`` pass.
The IR pipeline keeps that contract: we still want to know which
attachments the body references so a single page export does not need to
walk every attachment on the server.

This module holds the dataclass and a small walker that pulls it out of
an IR ``Document``.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING, Any

from mdd.ir.nodes import ConfluenceImage, ConfluenceLink

if TYPE_CHECKING:
    from mdd.ir.document import Document


@dataclass
class AttachmentRef:
    """A reference to a page attachment found in the body."""

    filename: str


def collect_attachment_refs(doc: Document) -> list[AttachmentRef]:
    """Walk *doc* and return one ``AttachmentRef`` per ``ri:attachment`` use.

    Both ``<ac:image><ri:attachment .../></ac:image>`` and
    ``<ac:link><ri:attachment .../></ac:link>`` count. Duplicate filenames
    are preserved (the caller's downloader deduplicates by sha).
    """
    refs: list[AttachmentRef] = []
    _walk(doc, refs)
    return refs


def _walk(obj: Any, refs: list[AttachmentRef]) -> None:
    if isinstance(obj, ConfluenceImage) and obj.source_kind == "attachment" and obj.source:
        refs.append(AttachmentRef(filename=obj.source))
    elif isinstance(obj, ConfluenceLink) and obj.target_kind == "attachment" and obj.target:
        refs.append(AttachmentRef(filename=obj.target))

    if hasattr(obj, "__dataclass_fields__"):
        for f in dataclass_fields(obj):
            val = getattr(obj, f.name)
            if isinstance(val, list):
                for item in val:  # pyright: ignore[reportUnknownVariableType]
                    _walk(item, refs)
            elif hasattr(val, "__dataclass_fields__"):
                _walk(val, refs)
