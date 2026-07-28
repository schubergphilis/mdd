"""Sync local image attachments to a Confluence page (update path)."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from mdd.utils.logging import get_logger

from ._types import AttachmentCollisionError, AttachmentManifestEntry
from ._version import extract_upload_version
from .scan import scan_local_image_refs
from .svg_publish import rasterize_and_upload_svg_images

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.confluence.client import ConfluenceClient

log = get_logger(__name__)


def _resolve_attachment_path(
    src: str,
    working_dir: Path,
    working_dir_resolved: Path,
    attachments_dir: Path | None,
) -> Path | None:
    """Resolve *src* to an absolute path, preferring ``attachments_dir`` for
    bare filenames (the ``mdd confluence export-page`` convention) but
    falling back to ``working_dir`` for legacy/explicit relative paths.

    Returns ``None`` for paths that escape the working directory.
    """
    candidates: list[Path] = []
    # A bare filename (no path separator) most likely targets the sibling
    # ``<page>-attachments/`` directory; try that first.
    if attachments_dir is not None and "/" not in src and "\\" not in src:
        candidates.append((attachments_dir / src).resolve())
    candidates.append((working_dir / src).resolve())

    for path in candidates:
        if not path.is_relative_to(working_dir_resolved):
            continue
        if path.exists():
            return path
    # Nothing on disk yet — return the first in-scope candidate so the caller
    # can warn with a meaningful path.
    for path in candidates:
        if path.is_relative_to(working_dir_resolved):
            return path
    return None


def _resolve_unique_basenames(
    local_srcs: list[str],
    working_dir: Path,
    working_dir_resolved: Path,
    attachments_dir: Path | None,
) -> dict[str, Path]:
    """Resolve each markdown image ref to an absolute path keyed by basename.

    Drops paths that escape the working directory (with a stderr warning) and
    raises ``AttachmentCollisionError`` when two different absolute paths
    share the same basename.
    """
    resolved: dict[str, Path] = {}
    for src in local_srcs:
        abs_path = _resolve_attachment_path(src, working_dir, working_dir_resolved, attachments_dir)
        if abs_path is None:
            log.warning(
                "skipping attachment reference %r: resolved path "
                "escapes the working directory (%s).",
                src,
                working_dir_resolved,
            )
            continue
        basename = abs_path.name
        existing = resolved.get(basename)
        if existing is not None and existing != abs_path:
            raise AttachmentCollisionError(
                f"Basename collision: {basename!r} maps to both {existing} and {abs_path}"
            )
        resolved[basename] = abs_path
    return resolved


def _warn_missing_attachment(basename: str, abs_path: Path) -> None:
    """Emit the stderr warning used when a referenced attachment is absent."""
    log.warning(
        "attachment %r referenced in markdown but not found at %s: "
        "skipping upload. The page may have a broken image reference after this update.",
        basename,
        abs_path,
    )


def sync_attachments_for_update(
    client: ConfluenceClient,
    page_id: str,
    body_md: str,
    working_dir: Path,
    manifest: list[AttachmentManifestEntry],
    *,
    attachments_dir: Path | None = None,
) -> tuple[list[AttachmentManifestEntry], str]:
    """Sync local image attachments to a Confluence page.

    1. Scan ``body_md`` for ``![*](*)`` local file references.
    2. Detect basename collisions (same filename, different content).
    3. For each local file:
       - Compute SHA-256.
       - If hash matches manifest entry → skip.
       - Otherwise upload via the v1 attachments endpoint.
    4. Rasterize any ``.svg`` referenced as a markdown image (issue #143 —
       Confluence does not render SVG inline) and upload the PNG alongside.
    5. Return the updated manifest entries (unchanged entries preserved) and
       the body to render.

    ``attachments_dir`` defaults to ``None``. When set (typically to
    ``working_dir / "<page>-attachments"``), bare filenames in the markdown
    are resolved there first — matching what ``mdd confluence export-page``
    writes to disk. Falls back to ``working_dir`` for legacy refs.

    Returns:
        A tuple of ``(updated manifest entries, body_md to render)``. The
        body is identical to the input unless a locally-referenced ``.svg``
        image was rasterized to PNG, in which case that image ref is
        rewritten to a ``confluence-attachment:`` URI for the PNG — callers
        must render *this* body, while still persisting the original,
        unrewritten ``body_md`` to disk.

    Raises:
        AttachmentCollisionError: if two different local paths share the same basename.
    """
    local_srcs = scan_local_image_refs(body_md)
    if not local_srcs:
        return list(manifest), body_md

    resolved = _resolve_unique_basenames(
        local_srcs, working_dir, working_dir.resolve(), attachments_dir
    )

    manifest_by_name: dict[str, AttachmentManifestEntry] = {e.filename: e for e in manifest}
    updated: dict[str, AttachmentManifestEntry] = dict(manifest_by_name)

    for basename, abs_path in resolved.items():
        if not abs_path.exists():
            _warn_missing_attachment(basename, abs_path)
            continue

        sha256 = hashlib.sha256(abs_path.read_bytes()).hexdigest()
        existing = manifest_by_name.get(basename)
        if existing is not None and existing.sha256 == sha256:
            # Hash matches — skip upload.
            continue

        result = client.upload_attachment(page_id, abs_path)
        updated[basename] = AttachmentManifestEntry(
            filename=basename,
            sha256=sha256,
            version=extract_upload_version(result),
        )

    svg_entries, rewritten_body = rasterize_and_upload_svg_images(
        client, page_id, body_md, resolved, manifest_by_name
    )
    updated.update(svg_entries)

    return list(updated.values()), rewritten_body
