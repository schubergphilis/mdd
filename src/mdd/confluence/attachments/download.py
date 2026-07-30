"""Download body-referenced attachments for a page (export path)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mdd.utils.logging import get_logger

from ._types import AttachmentManifestEntry
from ._version import extract_version

if TYPE_CHECKING:
    from mdd.confluence.client import ConfluenceClient
    from mdd.confluence.ir import AttachmentRef

log = get_logger(__name__)


def hash_file(path: Path) -> str:
    """Return hex SHA-256 of the file at *path*."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def conversion_needed(
    local: Path,
    manifest_entry: AttachmentManifestEntry | None,
    converter_version: str,
) -> bool:
    """Return True when the attachment needs (re-)conversion.

    Skips conversion when all of the following hold:
    - A manifest entry exists.
    - The entry's sha256 matches the current file on disk.
    - The entry's converter_version matches *converter_version*.
    - The converted output file exists on disk.
    """
    if manifest_entry is None:
        return True
    if manifest_entry.sha256 != hash_file(local):
        return True
    if manifest_entry.converter_version != converter_version:
        return True
    if not manifest_entry.converted_to:
        return True
    output = local.parent / manifest_entry.converted_to
    return not output.exists()


def _index_attachments_by_filename(
    attachments: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index attachment dicts by their ``title`` field (skipping nameless entries)."""
    by_filename: dict[str, dict[str, Any]] = {}
    for att in attachments:
        title_raw: Any = att.get("title")  # pyright: ignore[reportAny]
        if isinstance(title_raw, str) and title_raw:
            by_filename[title_raw] = att
    return by_filename


def _safe_destination(filename: str, attachments_dir: Path) -> Path | None:
    """Return the resolved destination path for *filename* under *attachments_dir*,
    or ``None`` when the name is degenerate or escapes the directory."""
    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        return None
    dest = attachments_dir / safe_name
    if not dest.resolve().is_relative_to(attachments_dir.resolve()):
        return None
    return dest


def _download_one(
    client: ConfluenceClient,
    att: dict[str, Any],
    dest: Path,
    *,
    page_id: str,
) -> bytes | None:
    """Download *att* to *dest*. Returns the bytes on success, ``None`` on
    failure (a stderr message is emitted so the caller can keep going)."""
    try:
        data = client.download_attachment(att)
        dest.write_bytes(data)
    except Exception as exc:
        # Per-attachment failure must not abort the whole page export
        # Mirror the sync_all_attachments pattern: log to
        # stderr, skip the manifest append, and continue with the next
        # reference so the markdown body still gets written by the
        # caller in export.py.
        log.exception("download %s (page %s): %s", dest.name, page_id, exc)
        return None
    return data


def download_for_page(
    client: ConfluenceClient,
    page_id: str,
    refs: list[AttachmentRef],
    out_dir: Path,
    page_name: str,
) -> list[AttachmentManifestEntry]:
    """Download attachments referenced by a page's markdown body.

    Args:
        client: Authenticated Confluence client.
        page_id: Confluence page ID.
        refs: List of attachment filenames referenced in the markdown.
        out_dir: Base output directory for the page.
        page_name: Sanitized page name (used to name the attachments subdir).

    Returns:
        List of manifest entries for downloaded attachments.
    """
    if not refs:
        return []

    by_filename = _index_attachments_by_filename(client.list_page_attachments(page_id))
    attachments_dir = out_dir / f"{page_name}-attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[AttachmentManifestEntry] = []
    for ref in refs:
        # Sanitise the filename to prevent path traversal: use only the basename
        # component and reject degenerate names (empty, ".", "..").  Final
        # defence: ensure the resolved destination stays inside attachments_dir.
        dest = _safe_destination(ref.filename, attachments_dir)
        if dest is None:
            continue
        att = by_filename.get(ref.filename)
        if att is None:
            # Referenced in markdown but not found on the page — skip.
            continue
        data = _download_one(client, att, dest, page_id=page_id)
        if data is None:
            continue
        manifest.append(
            AttachmentManifestEntry(
                filename=dest.name,
                sha256=hashlib.sha256(data).hexdigest(),
                version=extract_version(att),
            )
        )

    return manifest
