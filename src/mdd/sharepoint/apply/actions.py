"""Per-PairAction apply functions for SharePoint sync."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from mdd.sharepoint.diff import (
    read_sync_state,
    sha256_file,
    sha256_md_content,
)
from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter

from ._types import PairResult
from .convert import converter_version, do_convert, do_render
from .io import atomic_write_bytes, atomic_write_text, backup_office_file
from .sync_block import update_sync_block_in_md

if TYPE_CHECKING:
    from pathlib import Path


def apply_docx_to_md(
    docx_path: Path,
    md_path: Path,
    *,
    backup: bool = False,  # noqa: ARG001
    output_root: Path | None = None,  # noqa: ARG001
) -> PairResult:
    """Convert *docx_path* → Markdown; overwrite *md_path* and update sync block.

    The conversion result is written atomically.  The existing ``.md``'s
    non-sharepoint frontmatter and body are replaced by the converter output;
    the ``sharepoint.sync`` block is stamped fresh.
    """
    converter_name = f"docling-{docx_path.suffix.lstrip('.').lower()}"
    converter_ver = converter_version(docx_path.suffix)

    # Write converted body to a temp destination
    tmp_md = md_path.with_suffix(md_path.suffix + ".tmp")
    try:
        do_convert(docx_path, tmp_md)
        body = tmp_md.read_text(encoding="utf-8", errors="replace")
    finally:
        if tmp_md.exists():
            tmp_md.unlink()

    # Capture the user's existing update_office choice BEFORE we overwrite the
    # file — DOCX_TO_MD must not silently flip a pair back to office-only sync
    # just because the office side happened to change first.
    prior_update_office = read_sync_state(md_path).update_office

    # Preserve non-sharepoint frontmatter from existing .md if possible
    merged = _merge_body_with_existing_fm(body, md_path, docx_path)
    atomic_write_text(md_path, merged)

    # Stamp sync block — preserve the user's update_office preference.
    office_sha = sha256_file(docx_path)
    md_sha = sha256_md_content(md_path)
    update_sync_block_in_md(
        md_path,
        office_sha256=office_sha,
        md_sha256=md_sha,
        converter_version=converter_ver,
        converter=converter_name,
        update_office=prior_update_office,
    )

    return PairResult(
        action_taken="docx→md: converted",
        md_path=md_path,
        docx_path=docx_path,
    )


def apply_md_to_docx(
    docx_path: Path,
    md_path: Path,
    *,
    backup: bool = False,
    output_root: Path | None = None,
) -> PairResult:
    """Render *md_path* → office file; overwrite *docx_path* and update sync block.

    Backs up the existing *docx_path* first if *backup* is True.
    """
    if backup and docx_path.exists() and output_root is not None:
        backup_office_file(docx_path, output_root)

    # Render via Quarto to a temp destination.  The ``.tmp`` segment must precede
    # the office extension so the reverse-converter dispatcher (which looks at
    # ``dest.suffix``) and Quarto (which infers format from the output extension)
    # both still see ``.docx`` / ``.pptx``.
    tmp_docx = docx_path.with_name(f"{docx_path.stem}.tmp{docx_path.suffix}")
    try:
        do_render(md_path, tmp_docx)
        data = tmp_docx.read_bytes()
    finally:
        if tmp_docx.exists():
            tmp_docx.unlink()

    atomic_write_bytes(docx_path, data)

    # Stamp sync block (md authoritative → update_office stays True)
    office_sha = sha256_file(docx_path)
    md_sha = sha256_md_content(md_path)
    update_sync_block_in_md(
        md_path,
        office_sha256=office_sha,
        md_sha256=md_sha,
        converter_version=converter_version(docx_path.suffix),
        converter=f"quarto-{docx_path.suffix.lstrip('.').lower()}",
        update_office=True,
    )

    return PairResult(
        action_taken="md→docx: rendered",
        md_path=md_path,
        docx_path=docx_path,
    )


def apply_diverged(
    docx_path: Path,
    md_path: Path,
    *,
    last_sync: str | None = None,
) -> PairResult:
    """Handle divergence: write ``*.from-md.docx`` candidate, leave both sources untouched.

    If ``Foo.from-md.docx`` already exists (user is mid-merge), skip the render.
    """
    stem = docx_path.stem  # e.g. "Foo"
    ext = docx_path.suffix  # e.g. ".docx"
    candidate_name = f"{stem}.from-md{ext}"
    candidate_path = docx_path.parent / candidate_name
    editor_app = "PowerPoint" if ext.lower() == ".pptx" else "Word"

    if candidate_path.exists():
        # User is presumably mid-merge; don't re-render
        return PairResult(
            action_taken="diverged: candidate already exists, skipping re-render",
            md_path=md_path,
            docx_path=docx_path,
            divergence_candidate=candidate_path,
            warning=(
                f"{docx_path.name} and {md_path.name} both changed since "
                f"{last_sync or 'last sync'}. "
                f"A candidate render exists at {candidate_name}. "
                "Open both files, port changes manually, then re-run sync."
            ),
        )

    # Render .md → candidate docx (preserve office suffix; see apply_md_to_docx)
    tmp_cand = candidate_path.with_name(f"{candidate_path.stem}.tmp{candidate_path.suffix}")
    try:
        do_render(md_path, tmp_cand)
        data = tmp_cand.read_bytes()
    finally:
        if tmp_cand.exists():
            tmp_cand.unlink()

    atomic_write_bytes(candidate_path, data)

    return PairResult(
        action_taken="diverged: candidate written",
        md_path=md_path,
        docx_path=docx_path,
        divergence_candidate=candidate_path,
        warning=(
            f"{docx_path.name} and {md_path.name} both changed since {last_sync or 'last sync'}. "
            f"A candidate render of the latest .md is at {candidate_name}. "
            f"Open both files in {editor_app}, port changes manually, then re-run sync."
        ),
    )


def apply_first_sync_docx(
    docx_path: Path,
    md_path: Path,
) -> PairResult:
    """First-sync with office file authoritative: convert to .md and stamp sync block."""
    converter_name = f"docling-{docx_path.suffix.lstrip('.').lower()}"
    converter_ver = converter_version(docx_path.suffix)

    tmp_md = md_path.with_suffix(md_path.suffix + ".tmp")
    try:
        do_convert(docx_path, tmp_md)
        body = tmp_md.read_text(encoding="utf-8", errors="replace")
    finally:
        if tmp_md.exists():
            tmp_md.unlink()

    atomic_write_text(md_path, body)

    # Office file was authoritative for this first sync — leave the gate closed.
    office_sha = sha256_file(docx_path)
    md_sha = sha256_md_content(md_path)
    update_sync_block_in_md(
        md_path,
        office_sha256=office_sha,
        md_sha256=md_sha,
        converter_version=converter_ver,
        converter=converter_name,
        update_office=False,
    )

    return PairResult(
        action_taken="first-sync: docx→md",
        md_path=md_path,
        docx_path=docx_path,
    )


def apply_first_sync_md(
    docx_path: Path,
    md_path: Path,
    *,
    backup: bool = False,
    output_root: Path | None = None,
) -> PairResult:
    """First-sync with .md authoritative: render to office file and stamp sync block."""
    if backup and docx_path.exists() and output_root is not None:
        backup_office_file(docx_path, output_root)

    tmp_docx = docx_path.with_name(f"{docx_path.stem}.tmp{docx_path.suffix}")
    try:
        do_render(md_path, tmp_docx)
        data = tmp_docx.read_bytes()
    finally:
        if tmp_docx.exists():
            tmp_docx.unlink()

    atomic_write_bytes(docx_path, data)

    # Markdown was authoritative for this first sync — opt in to future renders.
    office_sha = sha256_file(docx_path)
    md_sha = sha256_md_content(md_path)
    update_sync_block_in_md(
        md_path,
        office_sha256=office_sha,
        md_sha256=md_sha,
        converter_version=converter_version(docx_path.suffix),
        converter=f"quarto-{docx_path.suffix.lstrip('.').lower()}",
        update_office=True,
    )

    return PairResult(
        action_taken="first-sync: md→docx",
        md_path=md_path,
        docx_path=docx_path,
    )


def apply_skip_md_update(
    docx_path: Path,
    md_path: Path,
    *,
    both_changed: bool,
) -> PairResult:
    """Record a skipped md→office render because ``update_office`` is False.

    Writes nothing; returns a :class:`PairResult` with a user-facing warning
    explaining how to opt the pair in (set ``update_office: true`` in the
    ``sharepoint.sync`` block of the .md frontmatter).
    """
    if both_changed:
        detail = (
            f"{docx_path.name} and {md_path.name} both changed since last sync, "
            "but update_office is False — both sources left untouched."
        )
    else:
        detail = (
            f"{md_path.name} changed but update_office is False — {docx_path.name} left untouched."
        )
    warning = (
        f"{detail} Set 'update_office: true' in the sharepoint.sync block of "
        f"{md_path.name} to allow md → office rendering for this pair."
    )
    return PairResult(
        action_taken="skip-md-update: update_office is False",
        md_path=md_path,
        docx_path=docx_path,
        warning=warning,
    )


def _merge_body_with_existing_fm(converted_body: str, md_path: Path, docx_path: Path) -> str:  # noqa: ARG001
    """Merge *converted_body* with any existing non-sharepoint frontmatter in *md_path*.

    If the existing .md has a non-sharepoint frontmatter block (e.g. Quarto title/author),
    we keep those keys and just replace the content body.  The sharepoint block
    will be stamped separately by ``update_sync_block_in_md``.

    If the existing file has no special frontmatter, or if it doesn't exist, return
    *converted_body* unchanged.
    """
    if not md_path.exists():
        return converted_body

    try:
        existing = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return converted_body

    split = split_frontmatter(existing)
    if split is None:
        return converted_body

    fm_block, _body_after = split
    mapping = parse_yaml_mapping(fm_block)
    if mapping is None:
        return converted_body

    fm_dict: dict[str, Any] = dict(mapping)
    # Drop sharepoint key — it will be re-stamped
    fm_dict.pop("sharepoint", None)
    if not fm_dict:
        # No other frontmatter to preserve
        return converted_body

    # Build merged: preserve existing non-sharepoint fm, use converted body
    conv_body_only = _strip_frontmatter(converted_body)
    merged_fm = yaml.safe_dump(
        fm_dict, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    return f"---\n{merged_fm}---\n{conv_body_only}"


def _strip_frontmatter(text: str) -> str:
    """Remove the leading YAML frontmatter block from *text* if present."""
    split = split_frontmatter(text)
    if split is None:
        return text
    _fm_block, body = split
    return body
