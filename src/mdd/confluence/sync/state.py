"""Desired-state fetch + parent-path mapping + cross-space probe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mdd.confluence.client import (
    MAX_PAGINATION_ITERATIONS,
    ConfluenceError,
    assert_relative_api_path,
)
from mdd.confluence.export import build_path_map
from mdd.confluence.sync_diff import DesiredPage
from mdd.confluence.tree import build_tree
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.confluence.client import ConfluenceClient

log = get_logger(__name__)


@dataclass(frozen=True)
class _VersionInfo:
    """Parsed ``version`` sub-object of a v2 page dict."""

    number: int = 1
    created_at: str = ""


def _parse_page_id(page: dict[str, Any]) -> str | None:
    """Extract a non-empty ``id`` string from a v2 page dict, or None if missing."""
    pid_raw: Any = page.get("id")  # pyright: ignore[reportAny]
    if isinstance(pid_raw, str) and pid_raw:
        return pid_raw
    return None


def _parse_title(page: dict[str, Any]) -> str:
    """Extract the ``title`` from a v2 page dict, defaulting to ``""``."""
    title_raw: Any = page.get("title", "")  # pyright: ignore[reportAny]
    return title_raw if isinstance(title_raw, str) else ""


def _parse_parent_id(page: dict[str, Any]) -> str | None:
    """Extract a non-empty ``parentId`` from a v2 page dict, or None if missing."""
    parent_id_raw: Any = page.get("parentId")  # pyright: ignore[reportAny]
    if isinstance(parent_id_raw, str) and parent_id_raw:
        return parent_id_raw
    return None


def _parse_status(page: dict[str, Any]) -> str:
    """Extract the upper-cased ``status`` from a v2 page dict, default ``CURRENT``."""
    status_raw: Any = page.get("status", "current")  # pyright: ignore[reportAny]
    if isinstance(status_raw, str):
        return status_raw.upper()
    return "CURRENT"


def _parse_version(page: dict[str, Any]) -> _VersionInfo:
    """Extract version number + createdAt from a v2 page dict's nested ``version`` object."""
    version_raw: Any = page.get("version")  # pyright: ignore[reportAny]
    if not isinstance(version_raw, dict):
        return _VersionInfo()
    vd: dict[str, Any] = version_raw  # pyright: ignore[reportUnknownVariableType]
    vn: Any = vd.get("number")  # pyright: ignore[reportAny]
    number = vn if isinstance(vn, int) else 1
    vcat: Any = vd.get("createdAt")  # pyright: ignore[reportAny]
    created_at = vcat if isinstance(vcat, str) and vcat else ""
    return _VersionInfo(number=number, created_at=created_at)


def _parse_space_id(page: dict[str, Any], default_space_id: str) -> str:
    """Extract ``spaceId`` from a v2 page dict, falling back to ``default_space_id``."""
    space_id_raw: Any = page.get("spaceId", default_space_id)  # pyright: ignore[reportAny]
    return space_id_raw if isinstance(space_id_raw, str) else default_space_id


def _parse_labels(page: dict[str, Any]) -> list[str]:
    """Extract label names from a v2 page dict's nested ``labels.results`` list."""
    labels_raw: Any = page.get("labels")  # pyright: ignore[reportAny]
    if not isinstance(labels_raw, dict):
        return []
    ld: dict[str, Any] = labels_raw  # pyright: ignore[reportUnknownVariableType]
    lr: Any = ld.get("results")  # pyright: ignore[reportAny]
    if not isinstance(lr, list):
        return []
    labels: list[str] = []
    for lbl in lr:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(lbl, dict):
            continue
        lbd: dict[str, Any] = lbl  # pyright: ignore[reportUnknownVariableType]
        ln: Any = lbd.get("name")  # pyright: ignore[reportAny]
        if isinstance(ln, str) and ln:
            labels.append(ln)
    return labels


def _desired_page_from_dict(page: dict[str, Any], default_space_id: str) -> DesiredPage | None:
    """Build a :class:`DesiredPage` from a v2 page dict, or None if it has no ``id``."""
    page_id = _parse_page_id(page)
    if page_id is None:
        return None
    version = _parse_version(page)
    return DesiredPage(
        page_id=page_id,
        title=_parse_title(page),
        parent_id=_parse_parent_id(page),
        status=_parse_status(page),
        version_number=version.number,
        version_created_at=version.created_at,
        space_id=_parse_space_id(page, default_space_id),
        labels=_parse_labels(page),
    )


def fetch_desired_state(
    client: ConfluenceClient,
    space_id: str,
    *,
    head: int | None = None,
) -> dict[str, DesiredPage]:
    """Fetch the desired state from Confluence (Step 1).

    Uses the v2 paginated endpoint with status=current,archived.
    """
    pages = list_pages_for_sync(client, space_id)

    desired: dict[str, DesiredPage] = {}
    for page in pages:
        if head is not None and len(desired) >= head:
            break
        dp = _desired_page_from_dict(page, space_id)
        if dp is None:
            continue
        desired[dp.page_id] = dp

    return desired


def _append_page_items(data: dict[str, Any], results: list[dict[str, Any]]) -> None:
    """Append the ``results`` entries from one v2 page-list response."""
    items_raw: Any = data.get("results", [])  # pyright: ignore[reportAny]
    if not isinstance(items_raw, list):
        return
    for item in items_raw:  # pyright: ignore[reportUnknownVariableType]
        if isinstance(item, dict):
            results.append(item)  # noqa: PERF401  # pyright: ignore[reportUnknownArgumentType]


def _next_page_path(data: dict[str, Any]) -> str | None:
    """Extract the ``_links.next`` path from one v2 page-list response."""
    links_raw: Any = data.get("_links", {})  # pyright: ignore[reportAny]
    if not isinstance(links_raw, dict):
        return None
    nxt: Any = links_raw.get("next")  # pyright: ignore[reportAny, reportUnknownVariableType, reportUnknownMemberType]
    if nxt is None:
        return None
    return str(nxt)  # pyright: ignore[reportUnknownArgumentType]


def list_pages_for_sync(
    client: ConfluenceClient,
    space_id: str,
) -> list[dict[str, Any]]:
    """Fetch all pages including current and archived (without bodies).

    The pagination loop is bounded by ``MAX_PAGINATION_ITERATIONS`` as a
    safety guard against runaway loops.
    """
    results: list[dict[str, Any]] = []
    # Confluence v2 query params are kebab-case: ``space-id``, not ``spaceId``
    # Atlassian silently *ignores* unknown params, so passing
    # ``spaceId`` would return every page in the tenant — fast path to an
    # infinite pagination loop.
    params: dict[str, str | int] | None = {
        "space-id": space_id,
        "status": "current,archived",
        "include-labels": "true",
        "include-version": "true",
        "limit": 250,
    }
    path = "/wiki/api/v2/pages"
    for _ in range(MAX_PAGINATION_ITERATIONS):
        # NOTE: ``params=None`` (not ``params={}``) on follow-up pages.
        # httpx interprets an empty dict as "replace the URL's query string
        # with these params", which would strip the cursor + space-id from
        # the ``_links.next`` URL and re-trigger the unfiltered tenant-wide
        # listing, which is how the runaway pagination loop happened.
        data = client.get(path, params=params)
        _append_page_items(data, results)
        next_path = _next_page_path(data)
        if not next_path:
            return results
        assert_relative_api_path(next_path, "_links.next")
        path = next_path
        params = None

    raise ConfluenceError(
        f"list_pages_for_sync(space_id={space_id}): pagination exceeded "
        f"{MAX_PAGINATION_ITERATIONS} iterations — possible runaway loop"
    )


def probe_cross_space(
    client: ConfluenceClient,
    page_ids: list[str],
    current_space_id: str,
) -> tuple[set[str], dict[str, str]]:
    """Probe pages that vanished from the tree to detect cross-space moves.

    Returns:
        Tuple of (cross_space_ids, dest_space_keys).
    """
    cross_space_ids: set[str] = set()
    dest_space_keys: dict[str, str] = {}

    for page_id in page_ids:
        try:
            page_data = client.get(
                f"/wiki/api/v2/pages/{page_id}",
                params={"include-version": "true"},
            )
        except ConfluenceError:
            # 404 or other error → truly deleted/trashed
            continue

        page_space_id: Any = page_data.get("spaceId")  # pyright: ignore[reportAny]
        if isinstance(page_space_id, str) and page_space_id and page_space_id != current_space_id:
            cross_space_ids.add(page_id)
            # Try to get space key
            try:
                space_data = client.get(
                    f"/wiki/api/v2/spaces/{page_space_id}",
                )
                key_raw: Any = space_data.get("key")  # pyright: ignore[reportAny]
                if isinstance(key_raw, str) and key_raw:
                    dest_space_keys[page_id] = key_raw
                else:
                    dest_space_keys[page_id] = page_space_id
            except ConfluenceError:
                dest_space_keys[page_id] = page_space_id

    return cross_space_ids, dest_space_keys


def build_parent_path_map(
    desired: dict[str, DesiredPage],
    client: ConfluenceClient,
    output_dir: Path,
) -> dict[str, Path]:
    """Build page_id → output directory mapping from the desired state.

    Uses the tree structure (parent_id chains) to compute nested paths.
    """
    # Build a Node-compatible structure from desired pages
    pages: list[dict[str, Any]] = [
        {
            "id": page.page_id,
            "title": page.title,
            "parentId": page.parent_id,
            "status": page.status.lower(),
            "position": None,
        }
        for page in desired.values()
    ]

    def folder_resolver(folder_id: str) -> dict[str, Any]:
        return client.get_folder(folder_id)

    warnings: list[str] = []
    roots = build_tree(pages, folder_resolver, warnings=warnings)
    for w in warnings:
        log.warning("%s", w)

    # Use export.py's path mapping logic
    used_dirs: dict[Path, set[str]] = {}
    return build_path_map(roots, output_dir, used_dirs)
