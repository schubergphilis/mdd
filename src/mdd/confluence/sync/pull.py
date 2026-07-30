"""Pull / new-page application: import remote pages, refresh local content."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.create import create_page
from mdd.confluence.export import export_page
from mdd.confluence.sync_diff import EventKind, SyncEvent
from mdd.utils.logging import get_logger

from .renames import resolve_path_after_rename

if TYPE_CHECKING:
    from collections.abc import Callable

    from mdd.confluence.config import ConfluenceConfig
    from mdd.confluence.managed import ManagedConfig

    from ._types import SyncOptions, SyncSummary

log = get_logger(__name__)


def _create_one_local(event: SyncEvent, config: ConfluenceConfig, summary: SyncSummary) -> None:
    if event.current_path is None:
        return
    local_path = Path(event.current_path)
    try:
        rc = create_page(local_path, config)
        if rc == 0:
            summary.new_pushed += 1
            log.info("create: %s", local_path.name)
        else:
            summary.failures.append(f"create {local_path.name}: create_page returned {rc}")
    except Exception as exc:
        log.exception("create %s: %s", local_path.name, exc)
        summary.failures.append(f"create {local_path.name}: {exc}")


def create_local_pages(
    events: list[SyncEvent], config: ConfluenceConfig, opts: SyncOptions, summary: SyncSummary
) -> None:
    for event in events:
        if event.kind != EventKind.NEW or event.page_id != "" or event.current_path is None:
            continue
        if opts.read_only:
            log.info("skip-create: %s (--read-only)", Path(event.current_path).name)
            continue
        _create_one_local(event, config, summary)


@dataclass
class PullCtx:
    """Cross-cutting state for content-pull/export helpers (keeps PLR0913 happy)."""

    client: ConfluenceClient
    page_to_outdir: dict[str, Path]
    output_dir: Path
    opts: SyncOptions
    summary: SyncSummary
    get_managed_cfg: Callable[[], ManagedConfig]


def create_remote_pages(events: list[SyncEvent], ctx: PullCtx) -> None:
    for event in events:
        if event.kind != EventKind.NEW or event.page_id == "" or event.desired is None:
            continue
        page_id = event.page_id
        out_dir_for_page = ctx.page_to_outdir.get(page_id, ctx.output_dir)
        try:
            exported_path = export_page(
                ctx.client,
                page_id,
                out_dir_for_page,
                max_attachment_size_bytes=ctx.opts.max_attachment_size_bytes,
                managed_config=ctx.get_managed_cfg(),
                skip_attachments=ctx.opts.skip_attachments,
            )
            ctx.summary.new_from_confluence += 1
            log.info("new: %s", exported_path.name)
        except (ConfluenceError, OSError) as exc:
            log.error("new %s: %s", page_id, exc)
            ctx.summary.failures.append(f"new {page_id}: {exc}")


def _pull_one_content(
    event: SyncEvent,
    mirror: Any,
    ctx: PullCtx,  # pyright: ignore[reportAny]
) -> None:
    if event.desired is None or event.current_path is None:
        return
    page_id = event.page_id
    current_path = resolve_path_after_rename(mirror, page_id, event.current_path)
    existing_att_manifest: list[dict[str, Any]] = []
    if page_id in mirror.tracked:  # pyright: ignore[reportAny]
        existing_att_manifest = mirror.tracked[page_id].attachments_manifest  # pyright: ignore[reportAny]
    try:
        export_page(
            ctx.client,
            page_id,
            current_path.parent,
            max_attachment_size_bytes=ctx.opts.max_attachment_size_bytes,
            existing_attachments_manifest=existing_att_manifest,
            managed_config=ctx.get_managed_cfg(),
            skip_attachments=ctx.opts.skip_attachments,
        )
        ctx.summary.content_pulled += 1
        log.info("pull: %s", current_path.name)
    except (ConfluenceError, OSError) as exc:
        log.error("pull %s: %s", page_id, exc)
        ctx.summary.failures.append(f"pull {page_id}: {exc}")


def pull_content(
    events: list[SyncEvent],
    mirror: Any,
    ctx: PullCtx,  # pyright: ignore[reportAny]
) -> None:
    for event in events:
        if event.kind == EventKind.CONTENT_EDIT:
            _pull_one_content(event, mirror, ctx)
