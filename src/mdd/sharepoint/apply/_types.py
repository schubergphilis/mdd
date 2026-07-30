"""Result dataclasses for SharePoint apply operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class PairResult:
    """Result from applying the action for one pair."""

    action_taken: str
    """Human-readable description of what happened."""

    md_path: Path
    """Path to the ``.md`` file (may have been created)."""

    docx_path: Path
    """Path to the office file (may have been created or left untouched)."""

    divergence_candidate: Path | None = None
    """Set when a ``*.from-md.docx`` candidate was written (DIVERGED)."""

    warning: str | None = None
    """Non-fatal warning message, if any."""


@dataclass
class SyncRunSummary:
    """Aggregated result of a full sync run."""

    first_sync_docx: int = 0
    """Pairs first-synced with docx as authoritative."""

    first_sync_md: int = 0
    """Pairs first-synced with .md as authoritative."""

    docx_to_md: int = 0
    """Pairs where docx changed → .md regenerated."""

    md_to_docx: int = 0
    """Pairs where .md changed → docx regenerated."""

    diverged: int = 0
    """Pairs where both sides changed."""

    no_op: int = 0
    """Pairs with no changes."""

    word_locked: int = 0
    """Pairs skipped because Word had the file open."""

    skipped_md_update: int = 0
    """Pairs where md changed but ``update_office`` was False — render skipped."""

    skipped_read_only: int = 0
    """Pairs where a mirror→SharePoint write was suppressed by ``--read-only``."""

    skipped_ignored: int = 0
    """Pairs (or pruned descendants) skipped because of ``.mddignore``."""

    pruned_ignored: int = 0
    """Already-synced files deleted by the ``--prune-ignored`` flag.

    ``skipped`` is source-side filtering; ``pruned`` is local cleanup of
    already-synced content. The two never overlap — under ``--dry-run``
    the counter still ticks up but no file is removed.
    """

    pruned_ignored_dry_run: bool = False
    """True when the prune pass ran under ``--dry-run`` (summary phrasing only)."""

    skipped_corrupt: int = 0
    """Pairs skipped because the office source is empty or not a valid Office package.

    Empty 0-byte files or files whose ZIP container cannot be opened
    by python-docx / python-pptx are recorded here rather than in ``errors`` so a
    handful of known-bad source files do not drown out genuine conversion errors.
    """

    errors: list[str] = field(default_factory=list)
    """Per-file error messages."""

    diverged_paths: list[str] = field(default_factory=list)
    """Relative paths of diverged pairs, for the commit message and summary."""

    skipped_md_paths: list[str] = field(default_factory=list)
    """Relative paths of pairs where md→office render was skipped."""

    skipped_read_only_paths: list[str] = field(default_factory=list)
    """Relative paths of pairs where a write was suppressed by ``--read-only``."""

    skipped_ignored_paths: list[str] = field(default_factory=list)
    """Source-relative paths skipped by ``.mddignore`` (sampled for log/debug)."""

    pruned_ignored_paths: list[str] = field(default_factory=list)
    """Dest-relative paths pruned by ``--prune-ignored``."""

    skipped_corrupt_paths: list[str] = field(default_factory=list)
    """Source-relative paths skipped because the office package is empty or corrupt."""

    def has_changes(self) -> bool:
        """Return True if any file was written (i.e. a git commit is warranted)."""
        return bool(
            self.first_sync_docx
            or self.first_sync_md
            or self.docx_to_md
            or self.md_to_docx
            or self.diverged
        )
