"""dispatch.py — per-action dispatchers for the bidirectional sync loop.

Split out of :mod:`mdd.sharepoint.sync` to keep that module under the
500-line watermark. The public entry points (``sync_folder`` / ``sync_site``)
remain in ``sync.py``; this module hosts the ``_apply_*`` helpers that route a
single ``(office, md)`` pair's :class:`~mdd.sharepoint.diff.PairAction` to the
correct ``apply`` function.

``sync.py`` re-imports :func:`apply_pair` at module top so existing test-patch
sites (``patch("mdd.sharepoint.sync.apply_pair", ...)``) continue to resolve.
The original symbol was named ``_apply_pair``; the underscore was dropped to
satisfy basedpyright's ``reportPrivateUsage`` on the cross-module import.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from mdd.sharepoint.apply import (
    apply_diverged,
    apply_docx_to_md,
    apply_first_sync_docx,
    apply_first_sync_md,
    apply_md_to_docx,
    apply_skip_md_update,
)
from mdd.sharepoint.diff import PairAction, classify_pair, read_sync_state, sha256_file
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.sharepoint.apply import SyncRunSummary
    from mdd.sharepoint.diff import SyncState


log = get_logger(__name__)


def _apply_skip_md_update(
    docx_path: Path,
    md_path: Path,
    *,
    summary: SyncRunSummary,
    sync_state: SyncState,
) -> None:
    both_changed = (
        sync_state.office_sha256_at_sync is not None
        and sha256_file(docx_path) != sync_state.office_sha256_at_sync
    )
    result = apply_skip_md_update(docx_path, md_path, both_changed=both_changed)
    summary.skipped_md_update += 1
    summary.skipped_md_paths.append(md_path.name)
    if result.warning:
        log.info(result.warning)


def _apply_diverged(
    docx_path: Path,
    md_path: Path,
    *,
    summary: SyncRunSummary,
    sync_state: SyncState,
) -> None:
    result = apply_diverged(docx_path, md_path, last_sync=sync_state.last_sync)
    summary.diverged += 1
    cand = result.divergence_candidate
    if cand is not None:
        summary.diverged_paths.append(cand.name)
    if result.warning:
        log.warning(result.warning)


def _apply_first_sync_docx(
    docx_path: Path,
    md_path: Path,
    *,
    summary: SyncRunSummary,
) -> None:
    apply_first_sync_docx(docx_path, md_path)
    summary.first_sync_docx += 1


def _apply_first_sync_md(
    docx_path: Path,
    md_path: Path,
    *,
    output_dir: Path,
    backup: bool,
    summary: SyncRunSummary,
) -> None:
    apply_first_sync_md(docx_path, md_path, backup=backup, output_root=output_dir)
    summary.first_sync_md += 1


def _is_write_to_sharepoint(action: PairAction) -> bool:
    """Return True for actions that write back to the OneDrive/SharePoint side."""
    return action in (
        PairAction.MD_TO_DOCX,
        PairAction.FIRST_SYNC_MD_AUTHORITATIVE,
        PairAction.MD_ONLY,
        PairAction.DIVERGED,
    )


def print_dry_run_plan(pairs: list[tuple[Path, Path]], *, read_only: bool) -> None:
    """Print the per-pair plan for ``--dry-run`` (optionally read-only).

    The plan goes to stdout as program output (intended to be piped/grepped),
    not through ``logging`` — keeping it stable for shell workflows. When the
    orchestrator enables ``T201`` in :file:`pyproject.toml`
    these calls will require a ``# noqa: T201  # program output for piping``
    marker.
    """
    header = "[dry-run] SharePoint sync plan"
    print(f"{header} (--read-only):" if read_only else f"{header}:")  # noqa: T201
    for docx_path, md_path in pairs:
        sync_state = read_sync_state(md_path)
        action = classify_pair(docx_path, md_path, sync_state=sync_state)
        suffix = (
            " [skip-write: --read-only]" if read_only and _is_write_to_sharepoint(action) else ""
        )
        print(f"  {docx_path.name} / {md_path.name} → {action}{suffix}")  # noqa: T201
    sys.stdout.flush()


def apply_pair(  # noqa: PLR0911, PLR0913
    *,
    action: PairAction,
    docx_path: Path,
    md_path: Path,
    output_dir: Path,
    backup: bool,
    read_only: bool,
    summary: SyncRunSummary,
    sync_state: SyncState,
) -> None:
    """Dispatch one pair action to the appropriate apply function and update *summary*."""
    if read_only and _is_write_to_sharepoint(action):
        log.info(
            "skip-write %s (--read-only, would have run %s)",
            docx_path.name,
            action,
        )
        summary.skipped_read_only += 1
        summary.skipped_read_only_paths.append(docx_path.name)
        return
    if action == PairAction.WORD_LOCKED:
        log.info(
            "skipping %s: file open in Word (lock file present)",
            docx_path.name,
        )
        summary.word_locked += 1
        return
    if action == PairAction.NO_OP:
        summary.no_op += 1
        return
    if action == PairAction.DOCX_TO_MD:
        apply_docx_to_md(docx_path, md_path, backup=backup, output_root=output_dir)
        summary.docx_to_md += 1
        return
    if action == PairAction.MD_TO_DOCX:
        apply_md_to_docx(docx_path, md_path, backup=backup, output_root=output_dir)
        summary.md_to_docx += 1
        return
    if action == PairAction.SKIP_MD_UPDATE:
        _apply_skip_md_update(docx_path, md_path, summary=summary, sync_state=sync_state)
        return
    if action == PairAction.DIVERGED:
        _apply_diverged(docx_path, md_path, summary=summary, sync_state=sync_state)
        return
    if action in (PairAction.FIRST_SYNC_DOCX_AUTHORITATIVE, PairAction.FIRST_SYNC_BOTH_DOCX_WINS):
        _apply_first_sync_docx(docx_path, md_path, summary=summary)
        return
    if action in (PairAction.FIRST_SYNC_MD_AUTHORITATIVE, PairAction.MD_ONLY):
        _apply_first_sync_md(
            docx_path, md_path, output_dir=output_dir, backup=backup, summary=summary
        )
