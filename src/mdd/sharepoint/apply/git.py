"""Git helpers for the sync output directory."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from mdd.utils.git import is_dirty, run_git

# Re-export ``is_dirty`` so existing ``from mdd.sharepoint.apply.git import is_dirty``
# (and the symbol-table mocking under tests/) keeps working (issue #123).
__all__ = ["git_commit", "is_dirty"]

if TYPE_CHECKING:
    from pathlib import Path

    from ._types import SyncRunSummary


def git_commit(output_dir: Path, summary: SyncRunSummary, site_name: str) -> str:
    """Stage and commit all changes in *output_dir*.

    Returns the new commit SHA, or an empty string if nothing was committed
    (including when *output_dir* is not yet a git work-tree — callers running
    without ``--push`` see the local mirror update without a noisy ``git add``
    failure).
    """
    if not (output_dir / ".git").exists():
        return ""

    # Stage everything; let GitError propagate as before.
    run_git(["add", "-A"], output_dir)

    # The "nothing to commit" branch needs the raw stdout/stderr from the
    # commit step, which run_git's GitError doesn't preserve verbatim. Keep
    # this call inline rather than fold it through run_git.
    msg = _build_commit_message(summary, site_name)
    result = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=str(output_dir),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
            return ""
        raise RuntimeError(f"git commit failed: {result.stderr.strip()}")

    return run_git(["rev-parse", "HEAD"], output_dir, timeout=10).stdout.strip()


def _build_commit_message(summary: SyncRunSummary, site_name: str) -> str:
    lines = [f"chore(mirror): sync from SharePoint site {site_name}", "", "Office <-> markdown:"]
    if summary.first_sync_docx:
        lines.append(f"  {summary.first_sync_docx} pairs first-synced (docx -> md)")
    if summary.first_sync_md:
        lines.append(f"  {summary.first_sync_md} pairs first-synced (md -> docx)")
    if summary.md_to_docx:
        lines.append(f"  {summary.md_to_docx} pairs: md edited -> docx regenerated")
    if summary.docx_to_md:
        lines.append(f"  {summary.docx_to_md} pairs: docx edited -> md regenerated")
    if summary.diverged:
        for p in summary.diverged_paths:
            lines.append(f"  1 pair: DIVERGED ({p} written for manual port)")  # noqa: PERF401
    return "\n".join(lines)
