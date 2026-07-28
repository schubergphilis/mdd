"""Atomic apply layer for SharePoint bidirectional sync (spec S18).

Each public function corresponds to one :class:`~mdd.sharepoint.diff.PairAction`.
All file writes are atomic (write to ``*.tmp``, then ``os.replace``).

Topic-grouped sub-modules: ``_types``, ``io``, ``sync_block``, ``convert``,
``actions``, ``git``, ``dry_run``.
"""

from __future__ import annotations

from ._types import PairResult, SyncRunSummary
from .actions import (
    apply_diverged,
    apply_docx_to_md,
    apply_first_sync_docx,
    apply_first_sync_md,
    apply_md_to_docx,
    apply_skip_md_update,
)
from .dry_run import print_dry_run_plan
from .git import git_commit, is_dirty
from .io import backup_office_file

__all__ = [
    "PairResult",
    "SyncRunSummary",
    "apply_diverged",
    "apply_docx_to_md",
    "apply_first_sync_docx",
    "apply_first_sync_md",
    "apply_md_to_docx",
    "apply_skip_md_update",
    "backup_office_file",
    "git_commit",
    "is_dirty",
    "print_dry_run_plan",
]
