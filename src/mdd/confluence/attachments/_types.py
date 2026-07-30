"""Public dataclasses and exception types for the attachments package."""

from __future__ import annotations

from dataclasses import dataclass, field


class AttachmentCollisionError(Exception):
    """Raised when two different local files share the same basename."""


@dataclass
class AttachmentManifestEntry:
    """Metadata about a downloaded attachment.

    Converter fields, all None unless the attachment was converted:
    - converted_to: filename of the converter output (e.g. "Foo.docx.md"), or None.
    - converter: converter name/ID (e.g. "docling-docx"), or None.
    - converter_version: version string of the converter, or None.
    """

    filename: str
    sha256: str
    version: int | str
    converted_to: str | None = field(default=None)
    converter: str | None = field(default=None)
    converter_version: str | None = field(default=None)


@dataclass
class AttachmentSyncSummary:
    """Per-page attachment sync statistics."""

    synced: int = 0
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    total_bytes: int = 0
