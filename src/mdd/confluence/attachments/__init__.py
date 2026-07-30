"""Download and upload Confluence page attachments.

Public surface (re-exported from topic-grouped sub-modules):

- :class:`AttachmentCollisionError` — basename collision exception.
- :class:`AttachmentManifestEntry`, :class:`AttachmentSyncSummary` — manifest dataclasses.
- :func:`conversion_needed`, :func:`download_for_page`, :func:`sync_all_attachments`,
  :func:`sync_attachments_for_update` — public entry points.
- :func:`rasterize_and_upload_svg_images` — SVG→PNG rasterization on publish (issue #143).

Topic-grouped sub-modules: ``_types``, ``download``, ``sync_all``, ``scan``, ``update``,
``svg_publish``.
"""

from __future__ import annotations

from ._types import AttachmentCollisionError, AttachmentManifestEntry, AttachmentSyncSummary
from .download import conversion_needed, download_for_page
from .svg_publish import rasterize_and_upload_svg_images
from .sync_all import sync_all_attachments
from .update import sync_attachments_for_update

__all__ = [
    "AttachmentCollisionError",
    "AttachmentManifestEntry",
    "AttachmentSyncSummary",
    "conversion_needed",
    "download_for_page",
    "rasterize_and_upload_svg_images",
    "sync_all_attachments",
    "sync_attachments_for_update",
]
