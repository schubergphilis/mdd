"""Bidirectional Confluence space sync orchestrator (spec S14).

Steps:
  1. Build desired state from Confluence (paginated tree fetch).
  2. Build current state from mirror (walk + frontmatter parse).
  3. Diff and classify (pure function).
  4. Apply changes (renames/moves/archives, new pages, edits, deletions).
  5. Commit.
  6. Optional push via mdd gitlab push.

Topic-grouped sub-modules:
- ``_types`` — :class:`SyncOptions`, :class:`SyncSummary`.
- ``_helpers`` — tiny cross-module helpers.
- ``state`` — desired-state fetch + parent-path map + cross-space probe.
- ``local_edits`` — detect locally-edited tracked pages.
- ``office_publish`` — spec S17 office-publish wiring.
- ``renames`` — RENAME / MOVE / ARCHIVE / UNARCHIVE application.
- ``pull`` — new-page / content-edit application.
- ``push`` — LOCAL_PUSH application.
- ``deletions`` — DELETED / CROSS_SPACE_MOVE application.
- ``finalize`` — conflicts, metadata refresh, commit, push, mirror state.
- ``events`` — diff classification + managed-helpers builder + phase runner.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mdd.confluence.apply import ApplyError, is_dirty, print_plan_summary
from mdd.confluence.tree import get_space_id
from mdd.utils.logging import get_logger

from ._types import SyncOptions, SyncSummary
from .events import apply_event_phases, classify_events, make_managed_helpers
from .finalize import (
    build_mirror_or_raise,
    finalize_commit_and_push,
    is_git_repo,
)
from .finalize import (
    # Re-exported for tests that ``patch("mdd.confluence.sync.push_to_gitlab", ...)``
    # against the old symbol-table seam (pre issue #132).
    push_to_gitlab as push_to_gitlab,
)
from .mddignore import filter_desired
from .office_publish import run_office_publish
from .pull import PullCtx
from .push import PushCtx
from .state import build_parent_path_map, fetch_desired_state

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.confluence.client import ConfluenceClient
    from mdd.confluence.config import ConfluenceConfig
    from mdd.confluence.sync_diff import DesiredPage

__all__ = ["SyncOptions", "SyncSummary", "sync_space"]

log = get_logger(__name__)

_DIRTY_TREE_MESSAGE = (
    "Mirror has uncommitted changes. Commit, stash, or discard before running sync."
)


def _run_prune_ignored(
    output_dir: Path,
    opts: SyncOptions,
    summary: SyncSummary,
) -> None:
    """Apply the spec S39 ``--prune-ignored`` pre-pass against *output_dir*.

    Walks the mirror tree once, deletes (or — under ``opts.dry_run`` — logs)
    every file the matcher marks ignored, and updates the summary counters.
    A missing matcher or an empty matcher is a no-op. Runs BEFORE the
    normal sync so ``--dry-run`` still reports the would-prune lines.
    """
    if opts.matcher is None:
        return
    summary.pruned_ignored_dry_run = opts.dry_run
    for path in opts.matcher.walk_prunable(output_dir):
        rel = path.relative_to(output_dir).as_posix()
        if opts.dry_run:
            log.info("would prune (ignored, dry-run): %s", rel)
        else:
            log.info("pruned (ignored): %s", rel)
            try:
                path.unlink()
            except OSError as exc:
                summary.failures.append(f"prune {rel}: {exc}")
                continue
        summary.pruned_ignored += 1
        summary.pruned_ignored_paths.append(rel)


def _apply_mddignore(
    desired: dict[str, DesiredPage],
    mirror: Any,  # pyright: ignore[reportAny, reportExplicitAny]
    opts: SyncOptions,
    client: ConfluenceClient,
    summary: SyncSummary,
) -> dict[str, DesiredPage]:
    """Apply the spec S39 ``.mddignore`` matcher to *desired* (issue #118).

    Drops new pages the matcher would ignore so they never become NEW
    events. Already-tracked pages are preserved — newly-added patterns
    never delete existing files (git-style "ignore-on-pull only"). With no
    matcher (or an empty matcher), this is a no-op and *desired* is
    returned unchanged.
    """
    if opts.matcher is None or not opts.matcher.sources:
        return desired
    filtered, skipped_paths = filter_desired(
        desired,
        set(mirror.tracked.keys()),  # pyright: ignore[reportAny]
        opts.matcher,
        client,
    )
    summary.skipped_ignored = len(skipped_paths)
    summary.skipped_ignored_paths = skipped_paths
    return filtered


def sync_space(
    client: ConfluenceClient,
    space_key: str,
    output_dir: Path,
    config: ConfluenceConfig,
    *,
    opts: SyncOptions | None = None,
) -> SyncSummary:
    """Full bidirectional reconciliation for a Confluence space.

    Args:
        client: Authenticated Confluence client.
        space_key: Confluence space key.
        output_dir: Mirror root directory.
        config: ConfluenceConfig (used for create_page/update_page).
        opts: Sync configuration (dry-run, head limit, push, read-only, ...).

    Returns:
        :class:`SyncSummary` with counts and notes.
    """
    if opts is None:
        opts = SyncOptions()
    summary = SyncSummary()

    # Dirty working tree check.
    if not opts.dry_run and is_dirty(output_dir):
        raise ApplyError(_DIRTY_TREE_MESSAGE)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Spec S39 opt-in cleanup. Runs BEFORE the normal sync so the
    # ``would prune (ignored, dry-run)`` lines still show up under
    # ``--dry-run`` and so the new pull does not re-fetch a page we
    # just deleted on disk in the same invocation.
    if opts.prune_ignored:
        _run_prune_ignored(output_dir, opts, summary)

    # Step 1: desired state from Confluence.
    space_id = get_space_id(client, space_key)
    desired = fetch_desired_state(client, space_id, head=opts.head)
    log.info("Fetched %d pages from Confluence space %r.", len(desired), space_key)

    # Step 2: current state from mirror.
    mirror = build_mirror_or_raise(output_dir, summary)
    desired = _apply_mddignore(desired, mirror, opts, client, summary)

    # Step 3: diff and classify.
    events, _locally_edited = classify_events(
        desired,
        mirror,
        output_dir,
        client,
        space_id,
        skip_attachments=opts.skip_attachments,
    )

    if opts.dry_run:
        print_plan_summary(events, head=opts.head)
        return summary

    # Step 4: apply changes.
    try:
        page_to_outdir = build_parent_path_map(desired, client, output_dir)
    except Exception as exc:
        log.warning("Could not build desired path map: %s", exc)
        page_to_outdir = {}
    used_paths: set[Path] = {p.path for p in mirror.tracked.values()}

    get_managed_cfg, record_managed_skip = make_managed_helpers(client, opts, summary)
    pull_ctx = PullCtx(
        client=client,
        page_to_outdir=page_to_outdir,
        output_dir=output_dir,
        opts=opts,
        summary=summary,
        get_managed_cfg=get_managed_cfg,
    )
    push_ctx = PushCtx(
        client=client,
        config=config,
        opts=opts,
        summary=summary,
        get_managed_cfg=get_managed_cfg,
        record_managed_skip=record_managed_skip,
    )
    apply_event_phases(events, mirror, pull_ctx, push_ctx, used_paths)

    # Step 4i: office publishing.
    if opts.read_only:
        log.info("Office publishing skipped (--read-only)")
    else:
        run_office_publish(
            client, mirror, config, summary, dry_run=False, managed_config=get_managed_cfg()
        )

    # Steps 5 + 6: commit + optional push, delegated to the mirror
    # orchestrator via finalize_commit_and_push.
    needs_init = opts.push and not is_git_repo(output_dir)
    if not summary.has_changes() and not summary.failures and not needs_init:
        return summary
    finalize_commit_and_push(output_dir, summary, space_key, opts.message, push=opts.push)
    return summary
