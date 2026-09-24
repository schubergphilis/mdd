"""Office-publish helpers wired into the sync pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mdd.confluence.frontmatter import read as read_frontmatter
from mdd.confluence.managed import (
    ManagedCheckError,
    ManagedConfig,
    classify_page,
    resolve_page_info,
    warn_managed,
)
from mdd.confluence.publish_office import OfficePublishCollisionError, publish
from mdd.confluence.update import update_page
from mdd.utils.logging import get_logger

from ._helpers import extract_storage_body

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.confluence.client import ConfluenceClient
    from mdd.confluence.config import ConfluenceConfig

    from ._types import SyncSummary

log = get_logger(__name__)


def _office_publish_candidate(md_path: Path) -> bool:
    """Return True if ``md_path``'s frontmatter opts in to office-publish."""
    if not md_path.exists():
        return False
    fm, _body = read_frontmatter(md_path)
    conf_raw: Any = fm.get("confluence")  # pyright: ignore[reportAny]
    if not isinstance(conf_raw, dict):
        return False
    conf: dict[str, Any] = conf_raw  # pyright: ignore[reportUnknownVariableType]
    return "publish_office" in conf


def _record_office_managed_skip(
    page_id: str,
    page_data: dict[str, Any],
    body_xhtml: str,
    client: ConfluenceClient,
    managed_config: ManagedConfig,
    summary: SyncSummary,
) -> bool:
    """If page is managed elsewhere, record and return True (sync should skip)."""
    try:
        page_info = resolve_page_info(client, page_data, body_xhtml, managed_config)
    except ManagedCheckError as exc:
        log.error("office-publish managed-check %s: %s", page_id, exc)
        summary.failures.append(f"office-publish managed-check {page_id}: {exc}")
        return True
    cl = classify_page(page_info, managed_config, client)
    if cl.restriction_check_unverified:
        summary.restriction_check_unverified += 1
    if not cl.is_managed:
        return False
    warn_managed(page_id, cl, context="office-publish")
    pub_key = cl.publisher_name or "_read_only"
    summary.managed_skips[pub_key] = summary.managed_skips.get(pub_key, 0) + 1
    return True


def _push_office_body_update(
    page_id: str, md_path: Path, config: ConfluenceConfig, dry_run: bool
) -> None:
    """Push the body-update that office-publish injected; warnings only on failure."""
    if dry_run:
        return
    try:
        rc = update_page(md_path, config, yes=True)
        if rc != 0:
            log.warning("office-publish body-update for %s returned %d", page_id, rc)
    except Exception as exc:
        log.warning("office-publish body-update %s: %s", page_id, exc)


@dataclass
class OfficePublishCtx:
    """Cross-cutting state for the office-publish phase (keeps PLR0913 happy)."""

    client: ConfluenceClient
    config: ConfluenceConfig
    summary: SyncSummary
    dry_run: bool = False
    managed_config: ManagedConfig | None = None


def _office_publish_one(page_id: str, md_path: Path, ctx: OfficePublishCtx) -> None:
    """Run office-publish for a single tracked page; record outcomes on ``ctx.summary``."""
    try:
        page_data = ctx.client.get_page(page_id)
        body_xhtml = extract_storage_body(page_data)
    except Exception as exc:
        log.exception("office-publish fetch %s: %s", page_id, exc)
        ctx.summary.failures.append(f"office-publish fetch {page_id}: {exc}")
        return

    if ctx.managed_config is not None and _record_office_managed_skip(
        page_id, page_data, body_xhtml, ctx.client, ctx.managed_config, ctx.summary
    ):
        return

    try:
        pub_summary = publish(
            ctx.client, page_id, md_path, body_xhtml, template_dir=None, dry_run=ctx.dry_run
        )
    except OfficePublishCollisionError as exc:
        log.error("office-publish collision %s: %s", page_id, exc)
        ctx.summary.failures.append(f"office-publish collision {page_id}: {exc}")
        return
    except Exception as exc:
        log.exception("office-publish %s: %s", page_id, exc)
        ctx.summary.failures.append(f"office-publish {page_id}: {exc}")
        return

    ctx.summary.failures.extend(pub_summary.failures)
    ctx.summary.office_uploaded += len(pub_summary.formats_uploaded)
    ctx.summary.office_cache_hits += len(pub_summary.formats_cache_hit)

    if pub_summary.body_xhtml != body_xhtml and pub_summary.formats_uploaded:
        _push_office_body_update(page_id, md_path, ctx.config, ctx.dry_run)


def run_office_publish(
    mirror: Any,
    ctx: OfficePublishCtx,  # pyright: ignore[reportAny]
    *,
    desired_ids: set[str],
) -> None:
    """Run publish_office for opted-in tracked pages that belong to the synced space.

    ``desired_ids`` is the set of page ids fetched for the synced space. A
    tracked file whose frontmatter names a page outside that set (for example
    one that survived a cross-space deletion under ``--no-delete``) is skipped
    and recorded in ``ctx.summary.office_skipped_outside_space``: sync-space
    only writes to the space it was asked to sync.

    Called after attachment sync and before the commit.
    Failures are recorded in ``ctx.summary.failures``; sync continues.
    """
    tracked: dict[str, Any] = mirror.tracked  # pyright: ignore[reportAny]
    for page_id, local_page in tracked.items():  # pyright: ignore[reportUnknownVariableType]
        md_path: Path = local_page.path  # pyright: ignore[reportAttributeAccessIssue]
        if not _office_publish_candidate(md_path):
            continue
        if page_id not in desired_ids:
            log.warning(
                "office-publish skipped %s (%s): page is not in the synced space",
                page_id,
                md_path,
            )
            ctx.summary.office_skipped_outside_space.append(f"{page_id}: {md_path}")
            continue
        _office_publish_one(page_id, md_path, ctx)
