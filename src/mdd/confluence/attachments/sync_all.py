"""Full-page attachment sync with converter cache (spec S16)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mdd.converters import converter_for as _registry_converter_for
from mdd.utils.logging import get_logger

from ._types import AttachmentManifestEntry, AttachmentSyncSummary
from .download import conversion_needed, hash_file

if TYPE_CHECKING:
    from mdd.confluence.client import ConfluenceClient
    from mdd.converters.protocol import Converter

log = get_logger(__name__)


@dataclass
class _PageSyncContext:
    """State shared across one page's attachment-sync loop."""

    client: ConfluenceClient
    page_id: str
    attachments_dir: Path
    existing: dict[str, AttachmentManifestEntry]
    summary: AttachmentSyncSummary
    max_attachment_size_bytes: int | None


def _extract_version(att: dict[str, Any]) -> int | str:
    """Extract the version number from an attachment dict."""
    version_raw: Any = att.get("version")  # pyright: ignore[reportAny]
    if isinstance(version_raw, dict):
        version_data: dict[str, Any] = dict(version_raw.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
        vn: Any = version_data.get("number")  # pyright: ignore[reportAny]
        return int(vn) if isinstance(vn, int) else 1
    if isinstance(version_raw, int):
        return version_raw
    return 1


def _extract_file_size(att: dict[str, Any]) -> int | None:
    """Extract file size from a v2 attachment dict (with v1 fallback).

    v2 puts ``fileSize`` at top level; v1 buried it under ``extensions``.
    """
    top_fs: Any = att.get("fileSize")  # pyright: ignore[reportAny]
    if isinstance(top_fs, int):
        return top_fs
    ext_raw: Any = att.get("extensions")  # pyright: ignore[reportAny]
    if isinstance(ext_raw, dict):
        ext_dict: dict[str, Any] = ext_raw  # pyright: ignore[reportUnknownVariableType]
        fs: Any = ext_dict.get("fileSize")  # pyright: ignore[reportAny]
        if isinstance(fs, int):
            return fs
    return None


def _coerce_existing_manifest(
    existing_manifest: list[dict[str, Any]],
) -> dict[str, AttachmentManifestEntry]:
    """Build a name → entry index from raw frontmatter-shaped manifest dicts."""
    existing: dict[str, AttachmentManifestEntry] = {}
    for entry_dict in existing_manifest:
        fn: Any = entry_dict.get("filename")  # pyright: ignore[reportAny]
        if not isinstance(fn, str) or not fn:
            continue
        sha: Any = entry_dict.get("sha256", "")  # pyright: ignore[reportAny]
        ver: Any = entry_dict.get("version", 1)  # pyright: ignore[reportAny]
        ct: Any = entry_dict.get("converted_to")  # pyright: ignore[reportAny]
        cv: Any = entry_dict.get("converter")  # pyright: ignore[reportAny]
        cvv: Any = entry_dict.get("converter_version")  # pyright: ignore[reportAny]
        existing[fn] = AttachmentManifestEntry(
            filename=fn,
            sha256=str(sha) if sha else "",
            version=int(ver) if isinstance(ver, int) else (str(ver) if ver else 1),
            converted_to=str(ct) if isinstance(ct, str) and ct else None,
            converter=str(cv) if isinstance(cv, str) and cv else None,
            converter_version=str(cvv) if isinstance(cvv, str) and cvv else None,
        )
    return existing


def _safe_destination(filename: str, attachments_dir: Path) -> Path | None:
    """Return a path-traversal-safe destination, or None if the name is unsafe."""
    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        return None
    dest = attachments_dir / safe_name
    if not dest.resolve().is_relative_to(attachments_dir.resolve()):
        return None
    return dest


def _exceeds_size_limit(
    att: dict[str, Any],
    safe_name: str,
    max_attachment_size_bytes: int | None,
) -> bool:
    """Return True (and print a [skip] line) if att exceeds the size limit."""
    if max_attachment_size_bytes is None:
        return False
    file_size = _extract_file_size(att)
    if file_size is None or file_size <= max_attachment_size_bytes:
        return False
    mb = file_size / (1024 * 1024)
    limit_mb = max_attachment_size_bytes / (1024 * 1024)
    log.warning("skip %s: %.1f MB exceeds --max-attachment-size %.0f MB", safe_name, mb, limit_mb)
    return True


def _converter_version(converter: Converter) -> str:
    """Return a converter's version string, falling back to its class name."""
    conv_ver = getattr(converter, "version", None)
    if conv_ver is None:
        conv_ver = type(converter).__name__
    return str(conv_ver)


def _apply_conversion(
    ctx: _PageSyncContext,
    converter: Converter,
    dest: Path,
    entry: AttachmentManifestEntry,
    cached_entry: AttachmentManifestEntry | None,
) -> None:
    """Run conversion (or reuse cached metadata) and mutate ``entry`` in place."""
    conv_ver = _converter_version(converter)
    if not conversion_needed(dest, cached_entry, conv_ver):
        if cached_entry is not None:
            entry.converted_to = cached_entry.converted_to
            entry.converter = cached_entry.converter
            entry.converter_version = cached_entry.converter_version
        return
    try:
        conv_result = converter.convert(dest)
        entry.converted_to = conv_result.output_path.name
        entry.converter = type(converter).__name__
        entry.converter_version = conv_ver
        ctx.summary.converted += 1
    except Exception as exc:
        log.exception("convert %s (page %s): %s", dest.name, ctx.page_id, exc)
        ctx.summary.failed += 1
        if cached_entry is not None:
            entry.converted_to = cached_entry.converted_to
            entry.converter = cached_entry.converter
            entry.converter_version = cached_entry.converter_version


def _sync_one_attachment(
    ctx: _PageSyncContext,
    att: dict[str, Any],
) -> AttachmentManifestEntry | None:
    """Process a single attachment through size/cache/download/convert.

    Mutates ``ctx.summary`` counters and writes to stderr on failure.  Returns
    the manifest entry to record for this attachment, or None if nothing should
    be appended (degenerate name, etc).
    """
    title_raw: Any = att.get("title")  # pyright: ignore[reportAny]
    filename: str = str(title_raw) if isinstance(title_raw, str) and title_raw else ""
    if not filename:
        return None

    dest = _safe_destination(filename, ctx.attachments_dir)
    if dest is None:
        return None
    safe_name = dest.name

    if _exceeds_size_limit(att, safe_name, ctx.max_attachment_size_bytes):
        ctx.summary.skipped += 1
        # Preserve any existing manifest entry so cache isn't lost
        return ctx.existing.get(safe_name)

    att_version = _extract_version(att)
    cached_entry = ctx.existing.get(safe_name)
    converter = _registry_converter_for(dest)

    # Skip the network round-trip when the cached file is still on disk at
    # the same Confluence version (the converter cache is checked separately).
    needs_download = not (
        cached_entry is not None and dest.exists() and cached_entry.version == att_version
    )

    if needs_download:
        try:
            ctx.client.download_attachment_to_file(att, dest)
        except Exception as exc:
            log.exception("download %s (page %s): %s", safe_name, ctx.page_id, exc)
            ctx.summary.failed += 1
            return ctx.existing.get(safe_name)

    if not dest.exists():
        ctx.summary.failed += 1
        return None

    file_hash = hash_file(dest)
    file_size = dest.stat().st_size
    ctx.summary.total_bytes += file_size
    if file_size > 10 * 1024 * 1024:
        mb = file_size / (1024 * 1024)
        log.info("%s: %.1f MB", safe_name, mb)

    entry = AttachmentManifestEntry(
        filename=safe_name,
        sha256=file_hash,
        version=att_version,
    )

    if converter is not None:
        _apply_conversion(ctx, converter, dest, entry, cached_entry)

    ctx.summary.synced += 1
    return entry


def sync_all_attachments(
    client: ConfluenceClient,
    page_id: str,
    attachments_dir: Path,
    existing_manifest: list[dict[str, Any]],
    *,
    max_attachment_size_bytes: int | None = None,
) -> tuple[list[AttachmentManifestEntry], AttachmentSyncSummary]:
    """Download ALL attachments for a page and run conversion on supported types.

    This is the spec S16 extension point called from export_page after the page
    body is fetched. Unlike download_for_page (which only downloads body-referenced
    images), this function:
    - Enumerates every attachment on the page via the Confluence API.
    - Downloads each (streaming, to avoid full-body buffering) unless:
      - SHA and converter_version match the cached manifest entry.
      - The attachment exceeds max_attachment_size_bytes.
    - Calls converter_for() on each downloaded file; runs conversion when needed.
    - On converter failure: logs a warning, skips the attachment, continues.

    Args:
        client: Authenticated Confluence client.
        page_id: Confluence page ID.
        attachments_dir: Directory to store attachments (created if absent).
        existing_manifest: The current ``attachments`` list from frontmatter.
        max_attachment_size_bytes: If set, skip downloads whose Content-Length
            exceeds this threshold (warn on skip).

    Returns:
        Tuple of (updated manifest entries, AttachmentSyncSummary).
    """
    all_attachments = client.list_page_attachments(page_id)
    if not all_attachments:
        return [], AttachmentSyncSummary()

    attachments_dir.mkdir(parents=True, exist_ok=True)

    ctx = _PageSyncContext(
        client=client,
        page_id=page_id,
        attachments_dir=attachments_dir,
        existing=_coerce_existing_manifest(existing_manifest),
        summary=AttachmentSyncSummary(),
        max_attachment_size_bytes=max_attachment_size_bytes,
    )
    result: list[AttachmentManifestEntry] = []
    for att in all_attachments:
        entry = _sync_one_attachment(ctx, att)
        if entry is not None:
            result.append(entry)
    return result, ctx.summary
