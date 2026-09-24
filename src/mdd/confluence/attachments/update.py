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


def _attachments_root(attachments_dir: Path) -> Path:
    """Return the page's attachments directory with only its parent resolved.

    The directory itself is deliberately not resolved: a symlinked
    ``<stem>-attachments`` then fails the containment test in
    :func:`_is_uploadable_path` instead of widening it to its target.
    """
    return attachments_dir.parent.resolve() / attachments_dir.name


def _resolve_attachment_path(
    src: str,
    working_dir: Path,
    attachments_root: Path,
) -> Path | None:
    """Resolve *src* to an absolute path inside the page's attachments directory.

    A bare filename is tried in the attachments directory first (the
    ``mdd confluence export-page`` convention), then relative to
    *working_dir*, so ``<stem>-attachments/x.png`` as written by the
    converters and the mermaid renderer resolves too.

    Returns ``None`` when no candidate lies inside *attachments_root*, or
    when the only candidates pass through a dot-prefixed component below it.
    """
    candidates: list[Path] = []
    if "/" not in src and "\\" not in src:
        candidates.append((attachments_root / src).resolve())
    candidates.append((working_dir / src).resolve())

    in_scope = [p for p in candidates if _is_uploadable_path(p, attachments_root)]
    for path in in_scope:
        if path.exists():
            return path
    # Nothing on disk yet: return the first in-scope candidate so the caller
    # can warn with a meaningful path.
    return in_scope[0] if in_scope else None


def _is_uploadable_path(path: Path, attachments_root: Path) -> bool:
    """True when *path* lies under the page's attachments directory and no
    component of the relative path starts with a dot (hidden files and
    directories such as ``.git/`` or ``.env`` are never upload sources)."""
    if not path.is_relative_to(attachments_root):
        return False
    relative = path.relative_to(attachments_root)
    return not any(part.startswith(".") for part in relative.parts)


def _warn_skipped_reference(src: str, attachments_root: Path) -> None:
    """Explain why *src* is not uploaded and how the operator can fix it."""
    log.warning(
        "skipping attachment reference %r: only files inside the page's own "
        "attachments folder %s are uploaded, and never dot-prefixed files or "
        "directories. To attach it, move the file into %s/ and reference it "
        "by its file name.",
        src,
        attachments_root,
        attachments_root.name,
    )


def _resolve_unique_basenames(
    local_srcs: list[str],
    working_dir: Path,
    attachments_root: Path,
) -> dict[str, Path]:
    """Resolve each markdown image ref to an absolute path keyed by basename.

    Drops references outside the page's attachments directory (with a
    warning) and raises ``AttachmentCollisionError`` when two different
    absolute paths share the same basename.
    """
    resolved: dict[str, Path] = {}
    for src in local_srcs:
        abs_path = _resolve_attachment_path(src, working_dir, attachments_root)
        if abs_path is None:
            _warn_skipped_reference(src, attachments_root)
            continue
        basename = abs_path.name
        existing = resolved.get(basename)
        if existing is not None and existing != abs_path:
            raise AttachmentCollisionError(
                f"Basename collision: {basename!r} maps to both {existing} and {abs_path}"
            )
        resolved[basename] = abs_path
    return resolved


def _warn_missing_attachment(basename: str, abs_path: Path, attachments_root: Path) -> None:
    """Emit the stderr warning used when a referenced attachment is absent."""
    log.warning(
        "attachment %r referenced in markdown but not found at %s: "
        "skipping upload. Only files inside the page's own attachments folder are "
        "uploaded; if the file lives elsewhere, move the file into %s/. "
        "The page may have a broken image reference after this update.",
        basename,
        abs_path,
        attachments_root.name,
    )


def sync_attachments_for_update(  # noqa: PLR0913
    client: ConfluenceClient,
    page_id: str,
    body_md: str,
    working_dir: Path,
    manifest: list[AttachmentManifestEntry],
    *,
    attachments_dir: Path,
    dry_run: bool = False,
) -> tuple[list[AttachmentManifestEntry], str]:
    """Sync local image attachments to a Confluence page.

    1. Scan ``body_md`` for ``![*](*)`` local file references.
    2. Detect basename collisions (same filename, different content).
    3. For each local file:
       - Compute SHA-256.
       - If hash matches manifest entry → skip.
       - Otherwise upload via the v1 attachments endpoint.
    4. Rasterize any ``.svg`` referenced as a markdown image (Confluence does
       not render SVG inline) and upload the PNG alongside.
    5. Return the updated manifest entries (unchanged entries preserved) and
       the body to render.

    ``attachments_dir`` is the page's own ``<stem>-attachments/`` directory
    beside the markdown file. Only files inside it are uploaded: bare
    filenames are looked up there first (what ``mdd confluence export-page``
    writes to disk), other references are resolved against ``working_dir``
    and must land inside it too. Anything else is skipped with a warning.

    With ``dry_run`` nothing is uploaded and no PNG is rasterized: every file
    that *would* be uploaded is logged with its size and hash instead, and the
    returned manifest carries the planned entries with ``version=0``. The
    returned body is rewritten exactly as it would be for a real sync, so
    callers can render the preview from it.

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

    attachments_root = _attachments_root(attachments_dir)
    resolved = _resolve_unique_basenames(local_srcs, working_dir, attachments_root)

    manifest_by_name: dict[str, AttachmentManifestEntry] = {e.filename: e for e in manifest}
    updated: dict[str, AttachmentManifestEntry] = dict(manifest_by_name)

    for basename, abs_path in resolved.items():
        if not abs_path.exists():
            _warn_missing_attachment(basename, abs_path, attachments_root)
            continue

        sha256 = hashlib.sha256(abs_path.read_bytes()).hexdigest()
        existing = manifest_by_name.get(basename)
        if existing is not None and existing.sha256 == sha256:
            # Hash matches — skip upload.
            continue

        if dry_run:
            log.info(
                "would upload attachment %s (%d bytes, sha256 %s) from %s",
                basename,
                abs_path.stat().st_size,
                sha256,
                abs_path,
            )
            updated[basename] = AttachmentManifestEntry(filename=basename, sha256=sha256, version=0)
            continue

        result = client.upload_attachment(page_id, abs_path)
        updated[basename] = AttachmentManifestEntry(
            filename=basename,
            sha256=sha256,
            version=extract_upload_version(result),
        )

    svg_entries, rewritten_body = rasterize_and_upload_svg_images(
        client, page_id, body_md, resolved, manifest_by_name, dry_run=dry_run
    )
    updated.update(svg_entries)

    return list(updated.values()), rewritten_body
