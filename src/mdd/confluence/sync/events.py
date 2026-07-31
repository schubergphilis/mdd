"""Event classification + managed-helpers builder + per-phase application."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mdd.confluence.managed import (
    ManagedConfig,
    build_page_info_from_page_data,
    classify_page,
    load_managed_config,
    warn_managed,
)
from mdd.confluence.sync_diff import (
    DesiredPage,
    EventKind,
    SyncEvent,
    compute_events,
    mark_conflicts,
    mark_cross_space_moves,
)

from ._helpers import extract_storage_body
from .deletions import apply_deletions
from .finalize import record_conflicts, refresh_metadata
from .local_edits import detect_local_edits
from .pull import PullCtx, create_local_pages, create_remote_pages, pull_content
from .push import PushCtx, push_content
from .renames import apply_archive_unarchive, apply_renames_moves
from .state import probe_cross_space

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mdd.confluence.client import ConfluenceClient

    from ._types import SyncOptions, SyncSummary


def upgrade_metadata_to_push(events: list[SyncEvent], locally_edited: set[str]) -> list[SyncEvent]:
    """Replace METADATA_ONLY events that are locally-edited with LOCAL_PUSH."""
    return [
        SyncEvent(
            kind=EventKind.LOCAL_PUSH,
            page_id=ev.page_id,
            desired=ev.desired,
            current_path=ev.current_path,
            current_version=ev.current_version,
        )
        if ev.kind == EventKind.METADATA_ONLY and ev.page_id in locally_edited
        else ev
        for ev in events
    ]


def classify_events(
    desired: dict[str, DesiredPage],
    mirror: Any,  # pyright: ignore[reportAny]
    output_dir: Path,
    client: ConfluenceClient,
    space_id: str,
    *,
    skip_attachments: bool = False,
) -> tuple[list[SyncEvent], set[str]]:
    """Run diff + conflict + cross-space + LOCAL_PUSH upgrade. Returns (events, locally_edited)."""
    locally_edited = detect_local_edits(mirror.tracked, desired, output_dir)  # pyright: ignore[reportAny]
    events = compute_events(
        desired,
        mirror.tracked,  # pyright: ignore[reportAny]
        mirror.untracked,  # pyright: ignore[reportAny]
        output_dir,
        skip_attachments=skip_attachments,
    )

    deleted_ids = [e.page_id for e in events if e.kind == EventKind.DELETED]
    if deleted_ids:
        cross_ids, dest_keys = probe_cross_space(client, deleted_ids, space_id)
        if cross_ids:
            events = mark_cross_space_moves(events, cross_ids, dest_space_keys=dest_keys)

    events = mark_conflicts(events, locally_edited)
    events = upgrade_metadata_to_push(events, locally_edited)
    return events, locally_edited


def make_managed_helpers(
    client: ConfluenceClient,
    opts: SyncOptions,
    summary: SyncSummary,
) -> tuple[Callable[[], ManagedConfig], Callable[[str, dict[str, Any]], bool]]:
    """Build the lazy ``_get_managed_cfg`` and ``_record_managed_skip`` closures."""
    managed_cfg_holder: list[ManagedConfig | None] = [opts.managed_config]

    def get_managed_cfg() -> ManagedConfig:
        if managed_cfg_holder[0] is None:
            managed_cfg_holder[0] = load_managed_config()
        return managed_cfg_holder[0]

    def record_managed_skip(page_id: str, page_data: dict[str, Any]) -> bool:
        body_storage = extract_storage_body(page_data)
        page_info = build_page_info_from_page_data(page_data, body_storage)
        cl = classify_page(page_info, get_managed_cfg(), client)
        if cl.restriction_check_unverified:
            summary.restriction_check_unverified += 1
        if not cl.is_managed:
            return False
        warn_managed(page_id, cl)
        pub_key = cl.publisher_name or "_read_only"
        summary.managed_skips[pub_key] = summary.managed_skips.get(pub_key, 0) + 1
        return True

    return get_managed_cfg, record_managed_skip


def apply_event_phases(
    events: list[SyncEvent],
    mirror: Any,  # pyright: ignore[reportAny]
    pull_ctx: PullCtx,
    push_ctx: PushCtx,
    used_paths: set[Path],
) -> None:
    """Run every Step-4 phase that mutates the mirror or pushes to Confluence."""
    apply_renames_moves(
        events,
        mirror,
        pull_ctx.output_dir,
        pull_ctx.page_to_outdir,
        used_paths,
        pull_ctx.summary,
    )
    apply_archive_unarchive(events, mirror, pull_ctx.summary)
    create_local_pages(events, push_ctx.config, pull_ctx.opts, pull_ctx.summary)
    create_remote_pages(events, pull_ctx)
    pull_content(events, mirror, pull_ctx)
    push_content(events, mirror, push_ctx)
    apply_deletions(events, pull_ctx.output_dir, pull_ctx.opts, pull_ctx.summary)
    record_conflicts(events, pull_ctx.summary)
    refresh_metadata(events, mirror, pull_ctx.summary)
