"""export.py — SharePoint site/folder walker and per-file rule dispatcher."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import yaml as _yaml

from mdd.convert import CorruptSourceError
from mdd.convert.pdf import convert_pdf
from mdd.convert.pptx import convert_pptx
from mdd.converters.docx import _write_docx  # pyright: ignore[reportPrivateUsage]
from mdd.mirror.protocol import MirrorTarget
from mdd.mirror.registry import default_backend
from mdd.sharepoint.frontmatter import write_frontmatter
from mdd.sharepoint.mapping import MappingEntry, repo_name
from mdd.sharepoint.rules import FileAction, decide
from mdd.sharepoint.sync import (
    SiteEntry,
    derive_site_name,
    list_sites,
    resolve_sync_root,
)
from mdd.utils.blacklist import check_sharepoint
from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter
from mdd.utils.logging import get_logger

log = get_logger(__name__)

_SSH_HOST_RE = re.compile(r"^git@([^:]+):(.+)$")


class ExportError(Exception):
    """Raised when export cannot proceed (e.g. site not found)."""


@dataclass
class ExportSummary:
    """Counters for an export run."""

    copied: int = 0
    converted: int = 0
    skipped: int = 0
    warned: int = 0
    errors: int = 0

    def __iadd__(self, other: ExportSummary) -> ExportSummary:
        self.copied += other.copied
        self.converted += other.converted
        self.skipped += other.skipped
        self.warned += other.warned
        self.errors += other.errors
        return self


@dataclass(frozen=True)
class _ExportContext:
    """Invariant per-run inputs for the file-walk loop.

    Bundles the site/output identity so the per-file helpers stay under the
    six-argument ceiling without juggling positional args.
    """

    site_root: Path
    site_name: str
    rn: str
    output_dir: Path
    force: bool


def _origin_url() -> str | None:
    """Return the CWD's ``origin`` remote URL, or ``None`` if there isn't one."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError, subprocess.TimeoutExpired:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _split_remote(url: str) -> tuple[str, str] | None:
    """Split a clone URL into ``(lowercased host, path)``, dropping any ``.git``.

    Handles both ``git@host:group/repo.git`` and ``https://host/group/repo.git``.
    Returns ``None`` for anything else.
    """
    ssh_match = _SSH_HOST_RE.match(url)
    if ssh_match:
        host, path = ssh_match.group(1), ssh_match.group(2)
    elif url.startswith(("https://", "http://")):
        parsed = urlsplit(url)
        host, path = parsed.hostname or "", parsed.path
    else:
        return None
    return host.lower(), path.strip("/").removesuffix(".git")


def default_output_for_site(site_name: str, mapping: dict[str, MappingEntry]) -> Path | None:
    """Return ``Path(".")`` if the CWD is a clone of *site_name*'s mirror remote.

    Uses ``git remote get-url origin`` to detect the repo and compares it
    against the URL the active :class:`~mdd.mirror.protocol.MirrorBackend`
    resolves for the site, so any deployment detects its own clone instead
    of being silently rejected.

    Returns ``None`` if detection fails or the URL does not match. Matching
    is done on host + path segments to prevent lookalike-domain attacks
    (e.g. ``evil.com/mdd/sharepoint/foo`` must not match).
    """
    origin = _origin_url()
    expected = default_backend().resolve_remote(
        MirrorTarget(kind="sharepoint", key=repo_name(site_name, mapping))
    )
    if origin is None or expected is None:
        return None

    actual_parts = _split_remote(origin)
    expected_parts = _split_remote(expected)
    if actual_parts is None or expected_parts is None or actual_parts != expected_parts:
        return None
    return Path()


def _sibling_md(file_path: Path) -> Path:
    """Return the expected sibling .md path for *file_path* (e.g. ``Foo.docx.md``)."""
    return file_path.parent / (file_path.name + ".md")


def _has_sibling_md(file_path: Path) -> bool:
    return _sibling_md(file_path).exists()


def _is_stale(src: Path, dst: Path) -> bool:
    """Return True if *dst* does not exist or is older than *src*."""
    if not dst.exists():
        return True
    return src.stat().st_mtime > dst.stat().st_mtime


def _exported_at_now() -> str:
    return datetime.now(UTC).isoformat()


def _source_mtime_str(path: Path) -> str:
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def _walk_site(site_root: Path) -> list[Path]:
    """Return all non-hidden files under *site_root*, sorted.

    Excludes any file whose path contains a component that starts with ``.``
    or ``._`` (e.g. ``.DS_Store``, ``._AppleDouble``, ``.fileloc``), matching
    the dotfile-skip logic in :func:`~mdd.sharepoint.sync.list_sites`.
    """
    return sorted(
        p
        for p in site_root.rglob("*")
        if p.is_file() and not any(part.startswith((".", "._")) for part in p.parts)
    )


def _apply_convert_docx(src: Path, dst: Path) -> None:  # pyright: ignore[reportUnusedFunction]
    """Convert a .docx to .md using the mdd convert pipeline.

    Resolved by name via :data:`_CONVERT_HANDLERS` / :func:`_resolve_convert_fn`;
    basedpyright cannot see the dynamic lookup so the unused-function diagnostic
    is suppressed here.
    """
    _write_docx(src, dst)


def _apply_convert_pptx(src: Path, dst: Path) -> None:  # pyright: ignore[reportUnusedFunction]
    """Convert a .pptx to .md (resolved by name; see :func:`_apply_convert_docx`)."""
    convert_pptx(src, dst)


def _apply_convert_pdf(src: Path, dst: Path) -> None:  # pyright: ignore[reportUnusedFunction]
    """Convert a .pdf to .md (resolved by name; see :func:`_apply_convert_docx`)."""
    convert_pdf(src, dst)


# Per-FileAction conversion handlers. Each entry pairs the name of the converter
# helper (looked up on this module so tests can monkeypatch ``_apply_convert_*``)
# with the converter tag written into SharePoint frontmatter.
_ConvertFn = Callable[[Path, Path], None]
_CONVERT_HANDLERS: dict[FileAction, tuple[str, str]] = {
    FileAction.CONVERT_DOCX: ("_apply_convert_docx", "docling-docx"),
    FileAction.CONVERT_PPTX: ("_apply_convert_pptx", "docling-pptx"),
    FileAction.CONVERT_PDF: ("_apply_convert_pdf", "docling-pdf"),
}


def _resolve_convert_fn(name: str) -> _ConvertFn:
    """Resolve a converter helper by name on this module.

    Indirection via name lookup keeps ``unittest.mock.patch`` working against
    ``mdd.sharepoint.export._apply_convert_*`` — a direct function reference
    captured at import time would shadow the patched attribute.
    """
    fn = globals()[name]
    return cast("_ConvertFn", fn)


def _dst_for_action(
    action: FileAction, output_dir: Path, rel: Path, file_path: Path, has_md: bool
) -> Path | None:
    """Compute the output path for *action*.

    Returns ``None`` when the file is superseded by a sibling .md (silent skip,
    not counted) so the caller advances to the next file.
    """
    if action in _CONVERT_HANDLERS:
        return output_dir / rel.parent / (rel.name + ".md")
    if action == FileAction.COPY_MARKDOWN:
        # If copying because of sibling .md, the sibling will be processed on its own turn.
        # Skip the office file silently (superseded by the .md, not a real skip).
        if has_md and file_path.suffix.lower() != ".md":
            return None
        return output_dir / rel
    # IGNORE / SKIP_WITH_WARNING — dst unused but kept for type-checker symmetry.
    return output_dir / rel


def _run_copy_markdown(file_path: Path, dst: Path, rel: Path, ctx: _ExportContext) -> None:
    """Copy a .md file to *dst*, stripping any pre-existing SharePoint frontmatter."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    body = _strip_sharepoint_frontmatter(content)
    _write_with_frontmatter(
        dst,
        ctx.site_name,
        ctx.rn,
        str(rel),
        _source_mtime_str(file_path),
        _exported_at_now(),
        "copy",
        body,
    )


def _run_convert(
    action: FileAction, file_path: Path, dst: Path, rel: Path, ctx: _ExportContext
) -> None:
    """Apply the converter registered for *action* and write SharePoint frontmatter."""
    convert_fn_name, converter_tag = _CONVERT_HANDLERS[action]
    _resolve_convert_fn(convert_fn_name)(file_path, dst)
    body = dst.read_text(encoding="utf-8", errors="replace")
    _write_with_frontmatter(
        dst,
        ctx.site_name,
        ctx.rn,
        str(rel),
        _source_mtime_str(file_path),
        _exported_at_now(),
        converter_tag,
        body,
    )


def _process_file(file_path: Path, ctx: _ExportContext, summary: ExportSummary) -> None:
    """Apply the per-file action for *file_path*, updating *summary* counters."""
    has_md = _has_sibling_md(file_path)
    action = decide(file_path, has_sibling_md=has_md)

    if action == FileAction.IGNORE:
        return
    if action == FileAction.SKIP_WITH_WARNING:
        log.warning("skipping unsupported file: %s", file_path)
        summary.warned += 1
        return

    rel = file_path.relative_to(ctx.site_root)
    dst = _dst_for_action(action, ctx.output_dir, rel, file_path, has_md)
    if dst is None:
        return

    if not ctx.force and not _is_stale(file_path, dst):
        summary.skipped += 1
        return

    try:
        if action == FileAction.COPY_MARKDOWN:
            _run_copy_markdown(file_path, dst, rel, ctx)
            summary.copied += 1
        elif action in _CONVERT_HANDLERS:
            _run_convert(action, file_path, dst, rel, ctx)
            summary.converted += 1
    except CorruptSourceError:
        # Empty or non-Office-ZIP source — soft skip instead
        # of a hard error so the run summary stays meaningful.
        log.info("skipping %s: corrupt or empty source", file_path)
        summary.skipped += 1
    except Exception as exc:
        log.error("%s: %s", file_path, exc)
        summary.errors += 1


def _export_files(ctx: _ExportContext, all_files: list[Path], summary: ExportSummary) -> None:
    """Walk *all_files* and apply per-file actions into ``ctx.output_dir``."""
    for file_path in all_files:
        _process_file(file_path, ctx, summary)


def _strip_sharepoint_frontmatter(content: str) -> str:
    """Remove existing *SharePoint* frontmatter block if present, return body only.

    Only strips the block if it contains a ``sharepoint:`` top-level key.
    Frontmatter belonging to other systems (Quarto, Jekyll, hand-written mdd
    confluence blocks) is left untouched.
    """
    split = split_frontmatter(content)
    if split is None:
        return content
    block, body = split
    # Only strip if the block is a SharePoint frontmatter block
    for line in block.splitlines():
        if line.startswith("sharepoint:"):
            return body
    return content


def _merge_sharepoint_into_frontmatter(  # noqa: PLR0913
    body: str,
    site_name: str,
    rn: str,
    source_rel: str,
    source_mtime: str,
    exported_at: str,
    converter: str,
) -> str:
    """Merge the ``sharepoint:`` key into an existing YAML frontmatter block in *body*.

    If *body* starts with ``---\\n``, the sharepoint subkey is inserted into the existing
    block instead of prepending a second block.  This preserves Quarto, Jekyll, and other
    frontmatter metadata.  Returns the merged content.

    If *body* does not start with ``---\\n``, returns ``None`` so the caller falls through
    to the normal (prepend) path.
    """
    split = split_frontmatter(body)
    if split is None:
        return body
    existing_block, body_after = split

    mapping = parse_yaml_mapping(existing_block)
    existing_dict: dict[str, object] = dict(mapping) if mapping is not None else {}
    existing_dict["sharepoint"] = {
        "site": site_name,
        "repo": rn,
        "source_path": source_rel,
        "source_mtime": source_mtime,
        "exported_at": exported_at,
        "converter": converter,
    }

    merged_fm = _yaml.safe_dump(
        existing_dict,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )

    export_date = exported_at[:10]
    callout = (
        f"> **SharePoint export**\n"
        f">\n"
        f"> This page was exported from `{site_name}/{source_rel}` on\n"
        f"> {export_date}. The master copy lives in SharePoint via OneDrive.\n"
    )
    return f"---\n{merged_fm}---\n{callout}\n{body_after}"


def _write_with_frontmatter(  # noqa: PLR0913
    dst: Path,
    site_name: str,
    rn: str,
    source_rel: str,
    source_mtime: str,
    exported_at: str,
    converter: str,
    body: str,
) -> None:
    """Write *body* to *dst* with SharePoint frontmatter.

    If *body* already has a non-SharePoint frontmatter block, the ``sharepoint:``
    key is merged into that block to avoid producing two ``---`` fences.
    Otherwise a fresh SharePoint frontmatter block is prepended.
    """
    if split_frontmatter(body) is not None:
        merged = _merge_sharepoint_into_frontmatter(
            body, site_name, rn, source_rel, source_mtime, exported_at, converter
        )
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dst.with_suffix(dst.suffix + ".tmp")
        tmp_path.write_text(merged, encoding="utf-8")
        os.replace(tmp_path, dst)  # noqa: PTH105
        return

    write_frontmatter(
        dst,
        site=site_name,
        repo=rn,
        source_path=source_rel,
        source_mtime=source_mtime,
        exported_at=exported_at,
        converter=converter,
        body=body,
    )


def export_site(
    site_name: str,
    *,
    config: object | None = None,
    mapping: dict[str, MappingEntry],
    output_dir: Path,
    force: bool = False,
    push: bool = False,
) -> ExportSummary:
    """Export a SharePoint site (by name) to a Markdown mirror.

    Steps:
      1. Resolve the sync root and find the matching :class:`SiteEntry`.
      2. Run the blacklist gate on the derived site name.
      3. Walk the site directory; apply per-file rules.
      4. If *push*: invoke ``push_worktree(output_dir)``.

    Args:
        site_name: The canonical (derived) site name to export.
        config: Optional config object with ``sharepoint.sync_root`` etc.
        mapping: Site→repo mapping (from :func:`~mdd.sharepoint.mapping.load_mapping`).
        output_dir: Root directory to write converted files into.
        force: Re-export even if the destination is up to date.
        push: Push the mirror via the active backend after export.

    Raises:
        ExportError: If the site cannot be found.
        BlacklistError: If the site name matches a blacklist entry.
    """
    sync_root = resolve_sync_root(config)
    sites = list_sites(sync_root)

    site_entry: SiteEntry | None = None
    for entry in sites:
        if entry.derived_site_name == site_name:
            site_entry = entry
            break

    if site_entry is None:
        available = [e.derived_site_name for e in sites]
        raise ExportError(
            f"Site {site_name!r} not found in sync root {sync_root}. Available sites: {available}"
        )

    # Blacklist gate BEFORE any file walk
    check_sharepoint(site_entry.derived_site_name)

    rn = repo_name(site_name, mapping)
    summary = ExportSummary()
    all_files = _walk_site(site_entry.path)
    ctx = _ExportContext(
        site_root=site_entry.path,
        site_name=site_name,
        rn=rn,
        output_dir=output_dir,
        force=force,
    )
    _export_files(ctx, all_files, summary)

    if push:
        default_backend().push(output_dir)

    return summary


def export_folder(
    local_path: Path,
    *,
    output_dir: Path,
    force: bool = False,
    push: bool = False,
    mapping: dict[str, MappingEntry] | None = None,
) -> ExportSummary:
    """Export an arbitrary local folder to a Markdown mirror.

    The site name is inferred from the leaf folder name (stripping ` - Documents`
    if present, mirroring :func:`~mdd.sharepoint.sync.list_sites` logic).
    The blacklist gate fires on the derived site name before any file is
    written to *output_dir*.

    Args:
        local_path: Path to the folder to export.
        output_dir: Root directory to write converted files into.
        force: Re-export even if the destination is up to date.
        push: Push the mirror via the active backend after export.
        mapping: Optional site→repo mapping.

    Raises:
        ExportError: If *local_path* does not exist or is not a directory.
        BlacklistError: If the derived site name matches a blacklist entry.
    """
    if not local_path.exists():
        raise ExportError(f"Path does not exist: {local_path}")
    if not local_path.is_dir():
        raise ExportError(f"Path is not a directory: {local_path}")

    m: dict[str, MappingEntry] = mapping if mapping is not None else {}
    site_name = derive_site_name(local_path.name)
    rn = repo_name(site_name, m)

    # Blacklist gate BEFORE any file walk (mirrors export_site behaviour)
    check_sharepoint(site_name)

    summary = ExportSummary()
    all_files = _walk_site(local_path)
    ctx = _ExportContext(
        site_root=local_path,
        site_name=site_name,
        rn=rn,
        output_dir=output_dir,
        force=force,
    )
    _export_files(ctx, all_files, summary)

    if push:
        default_backend().push(output_dir)

    return summary
