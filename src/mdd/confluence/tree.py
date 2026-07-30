"""Page tree builder for Confluence space export.

Also hosts the ancestor-walk used by :mod:`mdd.confluence.mutate`'s
``move-page`` implementation: :func:`ancestor_chain_for_move` returns
the chain of ancestors from the space root down to (and including) the
new parent, annotated with the local mirror's current representation
(``absent`` / ``flat`` / ``dir``) so the orchestrator can materialise
any missing links before doing the ``git mv``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from mdd.confluence.client import (
    MAX_PAGINATION_ITERATIONS,
    ConfluenceClient,
    ConfluenceError,
    assert_relative_api_path,
)
from mdd.confluence.paths import sanitize
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

log = get_logger(__name__)

AncestorState = Literal["absent", "flat", "dir"]


@dataclass(frozen=True)
class AncestorStep:
    """One link in the new parent's ancestor chain.

    Walking the chain top-to-bottom (space-root → ... → new parent),
    each step describes the mirror's current state for that ancestor:

    - ``absent``  — neither a flat ``Title.md`` nor a ``Title/`` directory
      exists at the expected location.  The orchestrator pulls the page
      from Confluence to materialise it.
    - ``flat``    — a flat ``Title.md`` sits at ``expected_dir.parent``
      (the page exists but has no children-directory yet).  The
      orchestrator promotes it to ``Title/_index.md`` so a child can
      live inside.
    - ``dir``     — ``expected_dir`` already exists with the page's
      ``_index.md`` (or, transitionally, just exists as a directory of
      children).  No materialisation needed.

    ``expected_dir`` is where this ancestor's children should land —
    i.e. the directory the next step down's flat ``.md`` (or the moved
    file, at the very end of the chain) will be written into.

    ``flat_md_path`` is the location of the page's flat ``.md`` form
    when ``state == "flat"`` (``None`` otherwise).  Held here so the
    promotion helper does not have to re-derive it.
    """

    page_id: str
    title: str
    expected_dir: Path
    state: AncestorState
    flat_md_path: Path | None = None


class Node(TypedDict):
    id: str
    type: str  # "page" or "folder"
    title: str
    position: int | None
    parent_id: str | None
    children: list[Node]


def get_space_id(client: ConfluenceClient, space_key: str) -> str:
    """Fetch the space ID for a given space key.

    GET /wiki/api/v2/spaces?keys=<space_key>

    Raises:
        ConfluenceError: If the space is not found.
    """
    data = client.get("/wiki/api/v2/spaces", params={"keys": space_key, "limit": 1})
    results_raw: Any = data.get("results")  # pyright: ignore[reportAny]
    if not isinstance(results_raw, list) or not results_raw:
        raise ConfluenceError(f"Space not found: {space_key!r}")
    first: Any = results_raw[0]  # pyright: ignore[reportAny, reportUnknownVariableType]
    if not isinstance(first, dict):
        raise ConfluenceError(f"Unexpected space result format for {space_key!r}")
    space_dict: dict[str, Any] = first  # pyright: ignore[reportUnknownVariableType]
    space_id_raw: Any = space_dict.get("id")  # pyright: ignore[reportAny]
    if not isinstance(space_id_raw, str) or not space_id_raw:
        raise ConfluenceError(f"Missing 'id' in space result for {space_key!r}")
    return space_id_raw


def _extend_with_dict_results(target: list[dict[str, Any]], data: dict[str, Any]) -> None:
    """Append every dict in ``data['results']`` to ``target`` (defensive isinstance)."""
    items_raw: Any = data.get("results", [])  # pyright: ignore[reportAny]
    if not isinstance(items_raw, list):
        return
    for item in items_raw:  # pyright: ignore[reportUnknownVariableType]
        if isinstance(item, dict):
            target.append(item)  # noqa: PERF401  # pyright: ignore[reportUnknownArgumentType]


def _next_pagination_path(data: dict[str, Any]) -> str | None:
    """Return ``_links.next`` from ``data`` when present and non-empty, else None."""
    links_raw: Any = data.get("_links", {})  # pyright: ignore[reportAny]
    if not isinstance(links_raw, dict):
        return None
    nxt: Any = links_raw.get("next")  # pyright: ignore[reportAny, reportUnknownVariableType, reportUnknownMemberType]
    if nxt is None:
        return None
    next_path = str(nxt)  # pyright: ignore[reportUnknownArgumentType]
    return next_path or None


def list_pages(client: ConfluenceClient, space_id: str) -> list[dict[str, Any]]:
    """Fetch all pages in a space, paginated.

    GET /wiki/api/v2/pages?spaceId=<space_id>&body-format=storage
        &include-labels=true&include-version=true

    Returns:
        Flat list of all page dicts (with bodies included).
    """
    results: list[dict[str, Any]] = []
    # Confluence v2 query params are kebab-case: ``space-id``, not ``spaceId``
    # See _list_pages_for_sync for the full rationale.
    params: dict[str, str | int] | None = {
        "space-id": space_id,
        "body-format": "storage",
        "include-labels": "true",
        "include-version": "true",
        "limit": 250,
    }
    path = "/wiki/api/v2/pages"
    for _ in range(MAX_PAGINATION_ITERATIONS):
        # ``params=None`` on follow-up pages — httpx treats ``params={}`` as
        # "replace the URL's query string", which strips the cursor in
        # ``_links.next``.  See _list_pages_for_sync for the full story.
        data = client.get(path, params=params)
        _extend_with_dict_results(results, data)
        next_path = _next_pagination_path(data)
        if next_path is None:
            return results
        # next must be a relative path — reject absolute URLs (SSRF guard)
        assert_relative_api_path(next_path, "_links.next")
        path = next_path
        params = None
    raise ConfluenceError(
        f"list_pages(space_id={space_id}): pagination exceeded "
        f"{MAX_PAGINATION_ITERATIONS} iterations — possible runaway loop"
    )


def _opt_str(value: Any) -> str | None:  # pyright: ignore[reportAny]
    """Return ``str(value)`` when value is a non-empty string, else None."""
    return str(value) if isinstance(value, str) and value else None


def _opt_int(value: Any) -> int | None:  # pyright: ignore[reportAny]
    """Return ``int(value)`` only when value is an int (bool excluded), else None."""
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _node_from_page(page: dict[str, Any]) -> Node | None:
    """Build a page :class:`Node` from a Confluence page dict.

    Returns ``None`` when the page has no string ``id`` (the page is then
    dropped from the tree).
    """
    page_id_raw: Any = page.get("id")  # pyright: ignore[reportAny]
    if not isinstance(page_id_raw, str):
        return None
    title_raw: Any = page.get("title", "")  # pyright: ignore[reportAny]
    return {
        "id": page_id_raw,
        "type": "page",
        "title": str(title_raw) if isinstance(title_raw, str) else "",
        "position": _opt_int(page.get("position")),  # pyright: ignore[reportAny]
        "parent_id": _opt_str(page.get("parentId")),  # pyright: ignore[reportAny]
        "children": [],
    }


def _node_from_folder(folder_id: str, folder_data: dict[str, Any]) -> Node:
    """Build a folder :class:`Node` from a folder-resolver response dict."""
    title_raw: Any = folder_data.get("title", "")  # pyright: ignore[reportAny]
    return {
        "id": folder_id,
        "type": "folder",
        "title": str(title_raw) if isinstance(title_raw, str) else "",
        "position": _opt_int(folder_data.get("position")),  # pyright: ignore[reportAny]
        "parent_id": _opt_str(folder_data.get("parentId")),  # pyright: ignore[reportAny]
        "children": [],
    }


@dataclass
class _TreeBuilder:
    """Mutable state for a single :func:`build_tree` invocation."""

    folder_resolver: Callable[[str], dict[str, Any]]
    warnings_sink: list[str] | None
    by_id: dict[str, Node] = field(default_factory=dict)
    folder_cache: dict[str, Node] = field(default_factory=dict)
    failed_folders: set[str] = field(default_factory=set)

    def emit_warning(self, msg: str) -> None:
        if self.warnings_sink is not None:
            self.warnings_sink.append(msg)
        else:
            log.warning("%s", msg)

    def get_or_fetch_folder(self, folder_id: str) -> Node:
        """Return the cached folder node or fetch + cache via ``folder_resolver``."""
        if folder_id in self.folder_cache:
            return self.folder_cache[folder_id]
        folder_data = self.folder_resolver(folder_id)
        folder_node = _node_from_folder(folder_id, folder_data)
        self.folder_cache[folder_id] = folder_node
        return folder_node

    def drain_folder_parents(self) -> None:
        """Recursively fetch every folder that is the parent of a known node."""
        seen_parents: set[str] = set()
        queue: list[Node] = list(self.by_id.values())
        while queue:
            node = queue.pop()
            pid = node["parent_id"]
            if (
                pid is None
                or pid in seen_parents
                or pid in self.by_id
                or pid in self.failed_folders
            ):
                continue
            seen_parents.add(pid)
            try:
                queue.append(self.get_or_fetch_folder(pid))
            except Exception as exc:
                self.failed_folders.add(pid)
                self.emit_warning(f"folder {pid!r} could not be fetched during tree build ({exc})")

    def parent_of(self, node: Node) -> Node | None:
        """Return ``node``'s parent Node, or None when the node is a root."""
        pid = node["parent_id"]
        if pid is None:
            return None
        if pid in self.by_id:
            return self.by_id[pid]
        if pid in self.folder_cache:
            return self.folder_cache[pid]
        if pid in self.failed_folders:
            return None
        try:
            return self.get_or_fetch_folder(pid)
        except Exception as exc:  # folder fetch failure → page promoted to root
            self.failed_folders.add(pid)
            self.emit_warning(
                f"folder {pid!r} could not be fetched ({exc}); "
                f"page {node['id']!r} ({node['title']!r}) promoted to root"
            )
            return None


def _sort_key(n: Node) -> tuple[int, str]:
    pos = n["position"]
    return (pos if pos is not None else sys.maxsize, n["title"])


def _sort_subtree(node: Node) -> None:
    """Sort children recursively by ``(position, title)``."""
    node["children"].sort(key=_sort_key)
    for child in node["children"]:
        _sort_subtree(child)


def build_tree(
    pages: list[dict[str, Any]],
    folder_resolver: Callable[[str], dict[str, Any]],
    *,
    warnings: list[str] | None = None,
) -> list[Node]:
    """Assemble a sorted page tree from a flat list of page dicts.

    The ``folder_resolver`` is called lazily for any parent ID that does not
    resolve to a known page (i.e., it is a folder node).  Results are cached
    internally so each folder ID is fetched at most once.

    Args:
        pages: Flat list of page dicts as returned by ``list_pages``.
        folder_resolver: Callable that accepts a folder ID and returns a dict
            with at least ``id``, ``title``, and ``type`` keys.
        warnings: Optional list to which human-readable warning strings are
            appended when a folder cannot be fetched.  Affected pages are
            promoted to root level.  When ``None``, warnings are printed to
            ``stderr`` instead.

    Returns:
        List of root ``Node`` dicts sorted by (position, title).  Each node's
        ``children`` list is similarly sorted.
    """
    builder = _TreeBuilder(folder_resolver=folder_resolver, warnings_sink=warnings)

    # Pass 1: index every valid page by id.
    for page in pages:
        node = _node_from_page(page)
        if node is not None:
            builder.by_id[node["id"]] = node

    # Pass 2: pull in any folder ancestors referenced by parent_id.
    builder.drain_folder_parents()

    # Pass 3: wire children to parents.  Reset children lists in case the
    # caller re-uses the same node objects across build_tree invocations.
    all_nodes: list[Node] = list(builder.by_id.values()) + list(builder.folder_cache.values())
    for n in all_nodes:
        n["children"] = []
    roots: list[Node] = []
    for node in all_nodes:
        parent = builder.parent_of(node)
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)

    # Pass 4: sort roots and every subtree.
    roots.sort(key=_sort_key)
    for root in roots:
        _sort_subtree(root)
    return roots


# ---------------------------------------------------------------------------
# Ancestor walk for ``move-page`` materialisation
# ---------------------------------------------------------------------------


def _safe_name(title: str, page_id: str) -> str:
    """Sanitize a Confluence title for use as a mirror filename/dir component.

    Matches the convention in :func:`build_path_map` / :func:`export_page`.
    Falls back to ``page-<id>`` when the title is empty.
    """
    return sanitize(title) if title else f"page-{page_id}"


def _classify_local_state(
    expected_dir: Path,
    safe: str,
) -> tuple[AncestorState, Path | None]:
    """Decide whether an ancestor's mirror presence is ``dir``, ``flat`` or ``absent``.

    The decision is purely filesystem-based and intentionally does not
    re-parse frontmatter: the walk only needs to know whether
    the *directory* exists (so a child can be placed inside) and, if not,
    whether a flat ``Title.md`` is available to promote.
    """
    if expected_dir.is_dir():
        return "dir", None
    flat = expected_dir.parent / f"{safe}.md"
    if flat.is_file():
        return "flat", flat
    return "absent", None


def _str_or_empty(d: dict[str, Any], key: str) -> str:
    """Return ``d[key]`` as a string, or ``""`` when missing / not a string."""
    raw: Any = d.get(key)  # pyright: ignore[reportAny]
    return raw if isinstance(raw, str) else ""


def _ancestor_in_space(entry: dict[str, Any], space_id: str) -> bool:
    """Return True when *entry*'s ``spaceId`` matches *space_id* (or is missing).

    A missing ``spaceId`` on the ancestor payload is treated as "same
    space" (Confluence sometimes omits it on space-root entries); a
    mismatch is a hard failure that callers translate into the
    cross-space refusal.
    """
    entry_space = _str_or_empty(entry, "spaceId")
    return not entry_space or entry_space == space_id


def ancestor_chain_for_move(
    client: ConfluenceClient,
    parent_id: str,
    space_id: str,
    output_dir: Path,
) -> list[AncestorStep]:
    """Build the new parent's ancestor chain annotated with mirror state.

    Walks ``GET /wiki/api/v2/pages/{parent_id}/ancestors`` to get every
    ancestor above ``parent_id`` (top-to-bottom), then appends the new
    parent itself so the returned list ends at the page that will hold
    the moved file.

    Each step's ``expected_dir`` is the directory under ``output_dir``
    where that ancestor's *children* live — i.e. the moved file goes
    into the **last** step's ``expected_dir``.

    Raises :class:`ConfluenceError` when any ancestor reports a
    ``spaceId`` that differs from ``space_id`` — that is a cross-space
    chain, which is refused.  Also raises when the parent page payload
    cannot be fetched.
    """
    ancestors = client.get_page_ancestors(parent_id)
    parent_data = client.get_page(parent_id)

    chain: list[AncestorStep] = []
    current_dir = output_dir
    for entry in ancestors:
        if not _ancestor_in_space(entry, space_id):
            raise ConfluenceError(
                f"ancestor {entry.get('id')!r} is in a different space; "
                "cross-space materialisation is not supported"
            )
        ancestor_id = _str_or_empty(entry, "id")
        if not ancestor_id:
            continue
        title = _str_or_empty(entry, "title")
        safe = _safe_name(title, ancestor_id)
        expected_dir = current_dir / safe
        state, flat = _classify_local_state(expected_dir, safe)
        chain.append(
            AncestorStep(
                page_id=ancestor_id,
                title=title,
                expected_dir=expected_dir,
                state=state,
                flat_md_path=flat,
            )
        )
        current_dir = expected_dir

    parent_title = _str_or_empty(parent_data, "title")
    parent_safe = _safe_name(parent_title, parent_id)
    parent_dir = current_dir / parent_safe
    parent_state, parent_flat = _classify_local_state(parent_dir, parent_safe)
    chain.append(
        AncestorStep(
            page_id=parent_id,
            title=parent_title,
            expected_dir=parent_dir,
            state=parent_state,
            flat_md_path=parent_flat,
        )
    )
    return chain
