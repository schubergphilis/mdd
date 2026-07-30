"""Push application: mirror → Confluence content updates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.sync_diff import EventKind, SyncEvent
from mdd.confluence.update import update_page
from mdd.utils.logging import get_logger

from .renames import resolve_path_after_rename

if TYPE_CHECKING:
    from collections.abc import Callable

    from mdd.confluence.config import ConfluenceConfig
    from mdd.confluence.managed import ManagedConfig

    from ._types import SyncOptions, SyncSummary

log = get_logger(__name__)


@dataclass
class PushCtx:
    """Cross-cutting state for content-push helpers (keeps PLR0913 happy)."""

    client: ConfluenceClient
    config: ConfluenceConfig
    opts: SyncOptions
    summary: SyncSummary
    get_managed_cfg: Callable[[], ManagedConfig]
    record_managed_skip: Callable[[str, dict[str, Any]], bool]


def _push_one(
    event: SyncEvent,
    mirror: Any,
    ctx: PushCtx,  # pyright: ignore[reportAny]
) -> None:
    if event.current_path is None:
        return
    if ctx.opts.read_only:
        log.info("skip-push: %s (--read-only)", Path(event.current_path).name)
        return
    page_id = event.page_id
    current_path = resolve_path_after_rename(mirror, page_id, event.current_path)
    try:
        page_data = ctx.client.get_page(page_id)
        if ctx.record_managed_skip(page_id, page_data):
            return
    except ConfluenceError as exc:
        log.error("push managed-check %s: %s", page_id, exc)
        ctx.summary.failures.append(f"push managed-check {page_id}: {exc}")
        return
    try:
        rc = update_page(current_path, ctx.config, yes=True, managed_config=ctx.get_managed_cfg())
        if rc == 0:
            ctx.summary.content_pushed += 1
            log.info("push: %s", current_path.name)
        else:
            ctx.summary.failures.append(f"push {page_id}: update_page returned {rc}")
    except Exception as exc:
        log.exception("push %s: %s", page_id, exc)
        ctx.summary.failures.append(f"push {page_id}: {exc}")


def push_content(
    events: list[SyncEvent],
    mirror: Any,
    ctx: PushCtx,  # pyright: ignore[reportAny]
) -> None:
    for event in events:
        if event.kind == EventKind.LOCAL_PUSH:
            _push_one(event, mirror, ctx)
