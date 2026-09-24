"""Pull / new-page application: import remote pages, refresh local content."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.create import create_page
from mdd.confluence.export import export_page
from mdd.confluence.frontmatter import read as read_frontmatter
from mdd.confluence.models import ConfluenceBlock
from mdd.confluence.sync_diff import EventKind, SyncEvent
from mdd.utils.logging import get_logger

from .renames import resolve_path_after_rename

if TYPE_CHECKING:
    from collections.abc import Callable

    from mdd.confluence.config import ConfluenceConfig
    from mdd.confluence.managed import ManagedConfig

    from ._types import SyncOptions, SyncSummary

log = get_logger(__name__)


def _frontmatter_block(md_path: Path) -> ConfluenceBlock | None:
    """Return the ``confluence:`` block a local file carries, or None if it has none."""
    frontmatter, _body = read_frontmatter(md_path)
    raw: object = frontmatter.get("confluence")
    if raw is None:
        return None
    return ConfluenceBlock.model_validate(raw)


@dataclass(frozen=True)
class CreateScope:
    """The space sync-space runs against; new pages are only created there."""

    client: ConfluenceClient
    space_key: str
    space_id: str


def _parent_space_id(client: ConfluenceClient, parent_id: str) -> str:
    """Return the space id of page or folder *parent_id*, or ``""`` if it cannot be found."""
    for fetch in (client.get_page, client.get_folder):
        try:
            data = fetch(parent_id)
        except ConfluenceError:
            continue
        space_id: Any = data.get("spaceId")  # pyright: ignore[reportAny]
        return space_id if isinstance(space_id, str) else ""
    return ""


def _other_space_reason(block: ConfluenceBlock | None, scope: CreateScope) -> str | None:
    """Return why a file must not be created in *scope*, or None if it may be."""
    if block is None:
        return None
    if block.space_key and block.space_key.casefold() != scope.space_key.casefold():
        return f"names space {block.space_key!r}, synced space is {scope.space_key}"
    if block.parent_id and _parent_space_id(scope.client, block.parent_id) != scope.space_id:
        return f"parent {block.parent_id!r} is not in the synced space {scope.space_key}"
    return None


def _create_one_local(
    event: SyncEvent, config: ConfluenceConfig, scope: CreateScope, summary: SyncSummary
) -> None:
    if event.current_path is None:
        return
    local_path = Path(event.current_path)
    try:
        reason = _other_space_reason(_frontmatter_block(local_path), scope)
        if reason is not None:
            log.warning("skip-create: %s %s", local_path.name, reason)
            summary.create_skipped_other_space.append(f"{local_path.name}: {reason}")
            return
        rc = create_page(local_path, config, space_key=scope.space_key)
        if rc == 0:
            summary.new_pushed += 1
            log.info("create: %s", local_path.name)
        else:
            summary.failures.append(f"create {local_path.name}: create_page returned {rc}")
    except Exception as exc:
        log.exception("create %s: %s", local_path.name, exc)
        summary.failures.append(f"create {local_path.name}: {exc}")


def create_local_pages(
    events: list[SyncEvent],
    config: ConfluenceConfig,
    opts: SyncOptions,
    summary: SyncSummary,
    *,
    scope: CreateScope,
) -> None:
    """Create a Confluence page in the synced space for every untracked local file.

    A file whose frontmatter names a different space, or a parent page or
    folder that is not in the synced space, is skipped and recorded in
    ``summary.create_skipped_other_space``: sync-space only creates pages in
    the space it was asked to sync.
    """
    for event in events:
        if event.kind != EventKind.NEW or event.page_id != "" or event.current_path is None:
            continue
        if opts.read_only:
            log.info("skip-create: %s (--read-only)", Path(event.current_path).name)
            continue
        _create_one_local(event, config, scope, summary)


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
                root=ctx.output_dir,
            )
            ctx.summary.new_from_confluence += 1
            log.info("new: %s", exported_path.name)
        except (ConfluenceError, OSError) as exc:
            log.error("new %s: %s", page_id, exc)
            ctx.summary.failures.append(f"new {page_id}: {exc}")
        except Exception as exc:
            # A page whose body cannot be parsed or rendered must not abort
            # the run: record it and continue with the remaining pages.
            log.exception("new %s: %s", page_id, exc)
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
            root=ctx.output_dir,
        )
        ctx.summary.content_pulled += 1
        log.info("pull: %s", current_path.name)
    except (ConfluenceError, OSError) as exc:
        log.error("pull %s: %s", page_id, exc)
        ctx.summary.failures.append(f"pull {page_id}: {exc}")
    except Exception as exc:
        # A page whose body cannot be parsed or rendered must not abort
        # the run: record it and continue with the remaining pages.
        log.exception("pull %s: %s", page_id, exc)
        ctx.summary.failures.append(f"pull {page_id}: {exc}")


def pull_content(
    events: list[SyncEvent],
    mirror: Any,
    ctx: PullCtx,  # pyright: ignore[reportAny]
) -> None:
    for event in events:
        if event.kind == EventKind.CONTENT_EDIT:
            _pull_one_content(event, mirror, ctx)
