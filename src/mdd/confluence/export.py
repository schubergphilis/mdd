"""Export a Confluence page or space to Markdown files."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from mdd.confluence.attachments import (
    AttachmentManifestEntry,
    AttachmentSyncSummary,
    download_for_page,
    sync_all_attachments,
)
from mdd.confluence.frontmatter import write as write_frontmatter
from mdd.confluence.ir import collect_attachment_refs, parse_confluence_storage
from mdd.confluence.managed import (
    ManagedClassification,
    ManagedConfig,
    build_page_info_from_page_data,
    classify_page,
    managed_export_header,
)
from mdd.confluence.paths import disambiguate, sanitize
from mdd.markdown.ir import render_markdown
from mdd.utils.blacklist import check_confluence
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from mdd.confluence.client import ConfluenceClient
    from mdd.confluence.ir.attachment_refs import AttachmentRef
    from mdd.confluence.tree import Node

log = get_logger(__name__)

_display_name_warned: bool = False


def _resolve_display_name(client: ConfluenceClient, account_id: str | None) -> str:
    """Fetch display name for an account ID.

    On the first failure (e.g. 401 token expiry, 403 forbidden, 5xx server error),
    prints a one-line warning to stderr with the exception message so the operator
    can diagnose token-expiry mid-export.  Subsequent failures are suppressed to
    avoid log spam.
    """
    global _display_name_warned

    if not account_id:
        return ""
    try:
        user = client.get_user(account_id)
        display_name: Any = user.get("displayName", "")  # pyright: ignore[reportAny]
        return str(display_name) if display_name else ""
    except Exception as exc:
        if not _display_name_warned:
            log.warning("display-name resolution failed for account %r: %s", account_id, exc)
            _display_name_warned = True
        return ""


def _str_or_empty(data: dict[str, Any], key: str) -> str:
    """Get a string value from a dict, returning empty string if missing or wrong type."""
    val: Any = data.get(key)  # pyright: ignore[reportAny]
    return str(val) if isinstance(val, str) and val else ""


def _nested_str(data: dict[str, Any], *keys: str) -> str:
    """Navigate nested dict by keys, returning a string or empty string."""
    current: Any = data  # pyright: ignore[reportAny]
    for key in keys:
        if not isinstance(current, dict):
            return ""
        d: dict[str, Any] = current  # pyright: ignore[reportUnknownVariableType]
        current = d.get(key)  # pyright: ignore[reportAny]
        if current is None:
            return ""
    return str(current) if isinstance(current, str) and current else ""


def _print_attachment_summary(summary: AttachmentSyncSummary) -> None:
    """Emit the per-page attachment summary line.

    Suppressed when nothing was synced — the all-zero line is pure noise
    on attachment-free pages.
    """
    if summary.synced <= 0:
        return
    total_mb = summary.total_bytes / (1024 * 1024)
    log.info(
        "%d attachments synced (%d converted, %d skipped, total %.1f MB)",
        summary.synced,
        summary.converted,
        summary.skipped,
        total_mb,
    )


def _stamp_attachments_skipped(conf_fm: dict[str, Any], *, skip_attachments: bool) -> None:
    """Set ``attachments_skipped: true`` on *conf_fm* when this export skipped attachments.

    No-op otherwise — the absence of the key on a normal re-export naturally
    clears the marker.
    """
    if skip_attachments:
        conf_fm["attachments_skipped"] = True


def make_page_url(base_url: str, space_key: str, page_id: str, title: str) -> str:
    """Build the canonical Confluence page URL.

    Uses ``quote`` to percent-encode all URL-special characters in the title,
    then replaces ``%20`` with ``+`` to match Confluence's slug style.
    """
    safe_title = quote(title, safe="").replace("%20", "+")
    return f"{base_url}/wiki/spaces/{space_key}/pages/{page_id}/{safe_title}"


@dataclass
class _PageMeta:
    """Per-page fields lifted out of the raw Confluence API response."""

    title: str
    status: str
    space_id: str
    space_key: str
    parent_id: str | None
    version_num: int
    updated_at: str
    updater_id: str | None
    labels: list[str] = field(default_factory=list)


@dataclass
class _ExportContext:
    """Per-call state threaded through the phase helpers of :func:`export_page`."""

    client: ConfluenceClient
    page_id: str
    out_dir: Path
    page_data: dict[str, Any]
    max_attachment_size_bytes: int | None
    existing_attachments_manifest: list[dict[str, Any]] | None
    managed_config: ManagedConfig | None
    include_export_header: bool
    skip_attachments: bool


def _extract_space_key(page_data: dict[str, Any]) -> str:
    """Return the space key, deriving from ``_links.webui`` when the field is absent."""
    space_key = _str_or_empty(page_data, "spaceKey")
    if space_key:
        return space_key
    webui = _nested_str(page_data, "_links", "webui")
    parts = [p for p in webui.split("/") if p]
    # Tolerate both /wiki/spaces/<KEY>/... and /spaces/<KEY>/...
    try:
        idx = parts.index("spaces")
    except ValueError:
        return ""
    if idx + 1 < len(parts):
        return parts[idx + 1]
    return ""


def _extract_version_info(page_data: dict[str, Any]) -> tuple[int, str, str | None]:
    """Return ``(version_num, updated_at, updater_id)`` from the ``version`` block."""
    version_raw: Any = page_data.get("version")  # pyright: ignore[reportAny]
    if not isinstance(version_raw, dict):
        return 1, "", None
    version_data: dict[str, Any] = version_raw  # pyright: ignore[reportUnknownVariableType]
    vn: Any = version_data.get("number")  # pyright: ignore[reportAny]
    version_num = int(vn) if isinstance(vn, int) else 1
    ua: Any = version_data.get("createdAt")  # pyright: ignore[reportAny]
    updated_at = str(ua) if isinstance(ua, str) and ua else ""
    aid: Any = version_data.get("authorId")  # pyright: ignore[reportAny]
    updater_id = str(aid) if isinstance(aid, str) and aid else None
    return version_num, updated_at, updater_id


def _extract_labels(page_data: dict[str, Any]) -> list[str]:
    """Return the list of label names from the ``labels.results`` block."""
    labels_raw: Any = page_data.get("labels")  # pyright: ignore[reportAny]
    if not isinstance(labels_raw, dict):
        return []
    labels_dict: dict[str, Any] = labels_raw  # pyright: ignore[reportUnknownVariableType]
    label_results: Any = labels_dict.get("results")  # pyright: ignore[reportAny]
    if not isinstance(label_results, list):
        return []
    result: list[str] = []
    for lbl in label_results:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(lbl, dict):
            continue
        lbl_d: dict[str, Any] = lbl  # pyright: ignore[reportUnknownVariableType]
        lbl_name: Any = lbl_d.get("name")  # pyright: ignore[reportAny]
        if isinstance(lbl_name, str) and lbl_name:
            result.append(lbl_name)
    return result


def _extract_body_storage(page_data: dict[str, Any]) -> str:
    """Return the ``body.storage.value`` XHTML string, or empty."""
    body_raw: Any = page_data.get("body")  # pyright: ignore[reportAny]
    if not isinstance(body_raw, dict):
        return ""
    body_dict: dict[str, Any] = body_raw  # pyright: ignore[reportUnknownVariableType]
    storage_raw: Any = body_dict.get("storage")  # pyright: ignore[reportAny]
    if not isinstance(storage_raw, dict):
        return ""
    storage_dict: dict[str, Any] = storage_raw  # pyright: ignore[reportUnknownVariableType]
    val: Any = storage_dict.get("value")  # pyright: ignore[reportAny]
    return str(val) if isinstance(val, str) else ""


def _extract_page_meta(page_data: dict[str, Any]) -> _PageMeta:
    """Pull all per-page metadata fields out of the raw API response."""
    parent_id_raw: Any = page_data.get("parentId")  # pyright: ignore[reportAny]
    parent_id = str(parent_id_raw) if parent_id_raw else None
    version_num, updated_at, updater_id = _extract_version_info(page_data)
    return _PageMeta(
        title=_str_or_empty(page_data, "title"),
        status=_str_or_empty(page_data, "status"),
        space_id=_str_or_empty(page_data, "spaceId"),
        space_key=_extract_space_key(page_data),
        parent_id=parent_id,
        version_num=version_num,
        updated_at=updated_at,
        updater_id=updater_id,
        labels=_extract_labels(page_data),
    )


def _sync_attachments(
    ctx: _ExportContext,
    page_name: str,
    attachment_refs: list[AttachmentRef],
) -> list[AttachmentManifestEntry]:
    """Download body-referenced images then sync all attachments."""
    img_manifest: list[AttachmentManifestEntry] = []
    if attachment_refs:
        img_manifest = download_for_page(
            ctx.client, ctx.page_id, attachment_refs, ctx.out_dir, page_name
        )

    page_attachments_dir = ctx.out_dir / f"{page_name}-attachments"
    all_manifest, att_summary = sync_all_attachments(
        ctx.client,
        ctx.page_id,
        page_attachments_dir,
        ctx.existing_attachments_manifest or [],
        max_attachment_size_bytes=ctx.max_attachment_size_bytes,
    )

    # Merge: all_manifest takes precedence; add any img_manifest entries not already included
    merged_filenames: set[str] = {e.filename for e in all_manifest}
    for img_entry in img_manifest:
        if img_entry.filename not in merged_filenames:
            all_manifest.append(img_entry)
            merged_filenames.add(img_entry.filename)

    _print_attachment_summary(att_summary)
    return all_manifest


def _build_page_url(
    client: ConfluenceClient,
    space_key: str,
    page_id: str,
    title: str,
    page_data: dict[str, Any],
) -> str:
    """Compute the canonical page URL, falling back to ``_links.webui``."""
    if space_key and page_id and title:
        return make_page_url(client.base_url, space_key, page_id, title)
    webui_link = _nested_str(page_data, "_links", "webui")
    if not webui_link:
        return ""
    # Ensure the /wiki/ prefix is present even when the tenant omits it
    if not webui_link.startswith("/wiki/"):
        webui_link = "/wiki/" + webui_link.lstrip("/")
    return client.base_url + webui_link


def _manifest_to_attachment_list(
    manifest: list[AttachmentManifestEntry],
) -> list[dict[str, Any]]:
    """Convert manifest entries to the dict shape stored in frontmatter."""
    attachments_list: list[dict[str, Any]] = []
    for e in manifest:
        entry_dict: dict[str, Any] = {
            "filename": e.filename,
            "sha256": e.sha256,
            "version": e.version,
        }
        if e.converted_to is not None:
            entry_dict["converted_to"] = e.converted_to
        if e.converter is not None:
            entry_dict["converter"] = e.converter
        if e.converter_version is not None:
            entry_dict["converter_version"] = e.converter_version
        attachments_list.append(entry_dict)
    return attachments_list


def _build_confluence_frontmatter(
    ctx: _ExportContext,
    meta: _PageMeta,
    *,
    page_url: str,
    exported_at: str,
    updated_by: str,
    attachments_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the ``confluence:`` block stored at the top of the exported markdown."""
    conf_fm: dict[str, Any] = {
        "url": page_url,
        "page_id": ctx.page_id,
        "space_key": meta.space_key,
        "space_id": meta.space_id,
        "parent_id": meta.parent_id,
        "status": meta.status,
        "version": meta.version_num,
        "updated_at": meta.updated_at,
        "updated_by": updated_by,
        "exported_at": exported_at,
    }
    if meta.labels:
        conf_fm["labels"] = meta.labels
    if attachments_list:
        conf_fm["attachments"] = attachments_list
    # Persist the "skipped under --no-attachments" marker so a
    # subsequent sync without that flag can back-fill attachments.  Cleared
    # naturally on the next full export (key simply isn't written).
    _stamp_attachments_skipped(conf_fm, skip_attachments=ctx.skip_attachments)
    return conf_fm


def _apply_managed_classification(
    ctx: _ExportContext,
    conf_fm: dict[str, Any],
    body_storage: str,
) -> ManagedClassification | None:
    """Classify the page and stamp ``managed_*`` keys when it is managed elsewhere."""
    if ctx.managed_config is None:
        return None
    page_info = build_page_info_from_page_data(ctx.page_data, body_storage)
    classification = classify_page(page_info, ctx.managed_config, ctx.client)
    if not classification.is_managed:
        return classification
    conf_fm["managed_by"] = classification.publisher_name or ""
    conf_fm["managed_source_url"] = classification.source_url or ""
    conf_fm["managed_reason"] = classification.reason.value if classification.reason else ""
    return classification


def _compose_export_header(
    *,
    include_export_header: bool,
    title: str,
    page_url: str,
    export_date: str,
    classification: ManagedClassification | None,
) -> str:
    """Return the leading export-callout block (empty when suppressed)."""
    if not include_export_header:
        return ""
    if classification is not None and classification.is_managed:
        return managed_export_header(classification, export_date)
    header_link = f"[{title}]({page_url})" if page_url else title
    return (
        f"> **Confluence export**\n"
        f">\n"
        f"> This page was exported from confluence page {header_link}\n"
        f"> on {export_date}. Check Confluence for the most up-to-date version.\n"
    )


def _compose_full_body(title: str, markdown_body: str, export_header: str) -> str:
    """Stitch the export header, H1 title, and rendered body into the file contents."""
    h1_line = f"# {title}\n\n" if title else ""
    body_section = f"{h1_line}{markdown_body}" if markdown_body else h1_line.strip()
    if not export_header:
        return body_section
    return f"{export_header}\n\n{body_section}" if body_section else export_header


def export_page(  # noqa: PLR0913
    client: ConfluenceClient,
    page_id: str,
    out_dir: Path,
    *,
    page_data: dict[str, Any] | None = None,
    max_attachment_size_bytes: int | None = None,
    existing_attachments_manifest: list[dict[str, Any]] | None = None,
    managed_config: ManagedConfig | None = None,
    include_export_header: bool = True,
    skip_attachments: bool = False,
) -> Path:
    """Export a single Confluence page to a Markdown file.

    Args:
        client: Authenticated Confluence client.
        page_id: The Confluence page ID to export.
        out_dir: Directory to write the output file into.
        page_data: Pre-fetched page data (optional; avoids a second API call).
        max_attachment_size_bytes: If set, skip attachment downloads above this
            size threshold (the ``--max-attachment-size`` flag).
        existing_attachments_manifest: Current attachments manifest from the
            local mirror's frontmatter (used as download/conversion cache).
        managed_config: When provided, classifies the page as
            managed-elsewhere or not, stamping frontmatter and replacing the
            export header when it is.
        include_export_header: When False, the leading ``> **Confluence
            export**`` blockquote is omitted. Useful for round-trip testing
            and other scripted exports where the header is noise rather
            than signal.
        skip_attachments: When True, skip *all* attachment downloads (both
            body-referenced images and the full per-page attachment sync).
            The frontmatter ``attachments:`` list will be empty.  Useful for
            text-only previews and for unblocking exports that fail on
            restricted attachments.

    Returns:
        Path to the written Markdown file.

    Raises:
        BlacklistError: If the page's space is on the confidentiality
            blacklist, or the space cannot be identified while any space is
            blacklisted.
        BlacklistConfigError: If no data-protection config declares the
            Confluence section.
    """
    if page_data is None:
        page_data = client.get_page(page_id)

    meta = _extract_page_meta(page_data)

    # Confidentiality gate before anything is written to disk. Placed here
    # rather than in the callers so every export path is covered: the
    # export-page command, sync's page pulls, and the ancestor materialisation
    # that move-page performs.
    check_confluence(meta.space_key)

    ctx = _ExportContext(
        client=client,
        page_id=page_id,
        out_dir=out_dir,
        page_data=page_data,
        max_attachment_size_bytes=max_attachment_size_bytes,
        existing_attachments_manifest=existing_attachments_manifest,
        managed_config=managed_config,
        include_export_header=include_export_header,
        skip_attachments=skip_attachments,
    )

    body_storage = _extract_body_storage(page_data)
    updated_by = _resolve_display_name(client, meta.updater_id)

    doc = parse_confluence_storage(body_storage)
    markdown_body = render_markdown(doc)
    attachment_refs = collect_attachment_refs(doc)

    page_name = sanitize(meta.title) if meta.title else f"page-{page_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if skip_attachments:
        manifest: list[AttachmentManifestEntry] = []
    else:
        manifest = _sync_attachments(ctx, page_name, attachment_refs)

    page_url = _build_page_url(client, meta.space_key, page_id, meta.title, page_data)
    exported_dt = datetime.now(UTC).replace(microsecond=0)
    exported_at = exported_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    conf_fm = _build_confluence_frontmatter(
        ctx,
        meta,
        page_url=page_url,
        exported_at=exported_at,
        updated_by=updated_by,
        attachments_list=_manifest_to_attachment_list(manifest),
    )
    classification = _apply_managed_classification(ctx, conf_fm, body_storage)

    export_header = _compose_export_header(
        include_export_header=include_export_header,
        title=meta.title,
        page_url=page_url,
        export_date=exported_at[:10],
        classification=classification,
    )
    full_body = _compose_full_body(meta.title, markdown_body, export_header)

    out_filename = f"{page_name}.md"
    out_path = disambiguate(out_dir / out_filename, page_id)
    write_frontmatter(out_path, {"confluence": conf_fm}, f"\n{full_body}\n")

    # Pin mtime to exported_at so that sync's local-edit heuristic
    # (mtime > exported_at ⇒ user touched the file) doesn't trip on
    # the write itself. The string in frontmatter is second-precision,
    # so the timestamp we apply must match exactly.
    exported_ts = exported_dt.timestamp()
    os.utime(out_path, (exported_ts, exported_ts))

    return out_path


def default_output_for_space(space_key: str) -> Path | None:
    """Return ``Path(".")`` when the CWD is a clone of the space mirror repo.

    Checks ``git remote get-url origin`` and matches the pattern
    ``mdd/confluence/<space-key>(.git)?`` anywhere in the URL.

    Returns:
        ``Path(".")`` if the CWD matches, ``None`` otherwise.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError, subprocess.TimeoutExpired:
        return None

    if result.returncode != 0:
        return None

    remote_url = result.stdout.strip()
    pattern = rf"mdd/confluence/{re.escape(space_key)}(?:\.git)?(?:/|$|#)"
    if re.search(pattern, remote_url) or remote_url.endswith(
        (f"mdd/confluence/{space_key}", f"mdd/confluence/{space_key}.git")
    ):
        return Path()
    return None


def build_path_map(
    nodes: list[Node],
    parent_dir: Path,
    used_dirs: dict[Path, set[str]],
) -> dict[str, Path]:
    """Recursively build a mapping of page id -> output directory.

    Folders become directories; pages get a directory corresponding to their
    position in the tree (children of a page go into a subdirectory named
    after the page's sanitized title).

    Args:
        nodes: List of sibling nodes at this level.
        parent_dir: Filesystem directory for the current level.
        used_dirs: Tracks used sanitized names per directory (for collision detection).

    Returns:
        Dict mapping page_id -> out_dir for each page node.
    """
    page_to_outdir: dict[str, Path] = {}

    for node in nodes:
        node_id = node["id"]
        title = node["title"]
        safe_name = sanitize(title) if title else node_id

        # Collision: same sanitized name at the same directory level
        if parent_dir not in used_dirs:
            used_dirs[parent_dir] = set()
        if safe_name in used_dirs[parent_dir]:
            safe_name = f"{safe_name}({node_id})"
        used_dirs[parent_dir].add(safe_name)

        if node["type"] == "folder":
            # Folders are pure directories
            folder_dir = parent_dir / safe_name
            page_to_outdir.update(build_path_map(node["children"], folder_dir, used_dirs))
        else:
            # Pages: the .md goes in parent_dir; children go in a subdir
            page_to_outdir[node_id] = parent_dir
            child_dir = parent_dir / safe_name
            page_to_outdir.update(build_path_map(node["children"], child_dir, used_dirs))

    return page_to_outdir
