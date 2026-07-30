"""Apply the ``.mddignore`` matcher to a Confluence sync (issue #118).

Confluence "directories" are not filesystem paths — they are page-title
hierarchies. For each page in the desired-state map we therefore build a
synthetic POSIX rel-path by walking the same title chain that
``build_path_map`` (in ``mdd.confluence.export``) uses to decide where the
page's markdown file lives on disk. That rel-path is the unit the matcher
sees.

Two filter passes:

1. ``prune_dir`` — when a page's *child subtree directory* (the directory
   in which its children live) is prunable, every descendant of that page
   is dropped from desired in one shot. This is the bulk-saving: an
   ``Archive/`` subtree never hits the per-page check.
2. ``is_ignored`` — every surviving page is checked individually. Pages
   already tracked locally are skipped: ignore only blocks new pulls, it
   never deletes already-synced files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from mdd.confluence.paths import sanitize
from mdd.confluence.tree import build_tree

if TYPE_CHECKING:
    from mdd.confluence.client import ConfluenceClient
    from mdd.confluence.sync_diff import DesiredPage
    from mdd.confluence.tree import Node
    from mdd.utils.mddignore import MddIgnore


@dataclass(frozen=True)
class _PageRel:
    """The two rel-paths the matcher needs for a single page node."""

    page_id: str
    md_rel: PurePosixPath  # rel-path of the page's ``<title>.md`` file
    child_rel: PurePosixPath  # rel-path of the directory holding children


def _node_rels(
    nodes: list[Node],
    parent_rel: PurePosixPath,
    used_names: dict[PurePosixPath, set[str]],
    out: dict[str, _PageRel],
) -> None:
    """Walk *nodes* mirroring ``export.build_path_map``'s naming/collision logic."""
    for node in nodes:
        node_id = node["id"]
        title = node["title"]
        safe = sanitize(title) if title else node_id
        used = used_names.setdefault(parent_rel, set())
        if safe in used:
            safe = f"{safe}({node_id})"
        used.add(safe)
        child_dir = parent_rel / safe
        if node["type"] == "folder":
            _node_rels(node["children"], child_dir, used_names, out)
            continue
        out[node_id] = _PageRel(
            page_id=node_id,
            md_rel=parent_rel / f"{safe}.md",
            child_rel=child_dir,
        )
        _node_rels(node["children"], child_dir, used_names, out)


def build_page_rel_paths(
    desired: dict[str, DesiredPage],
    client: ConfluenceClient,
) -> dict[str, _PageRel]:
    """Return ``page_id -> _PageRel`` for every page in *desired*.

    Builds the same Confluence tree that ``build_parent_path_map`` does but
    keeps both the markdown-file rel-path and the child-subtree rel-path so
    ``prune_dir`` can fire on the latter.
    """
    pages: list[dict[str, Any]] = [
        {
            "id": p.page_id,
            "title": p.title,
            "parentId": p.parent_id,
            "status": p.status.lower(),
            "position": None,
        }
        for p in desired.values()
    ]

    def folder_resolver(folder_id: str) -> dict[str, Any]:
        return client.get_folder(folder_id)

    roots = build_tree(pages, folder_resolver, warnings=[])
    out: dict[str, _PageRel] = {}
    used: dict[PurePosixPath, set[str]] = {}
    _node_rels(roots, PurePosixPath(), used, out)
    return out


def _compute_pruned_dirs(rels: dict[str, _PageRel], matcher: MddIgnore) -> set[PurePosixPath]:
    """Return the set of child-subtree rel-paths the matcher prunes wholesale.

    A Confluence page name like "Archive" doubles as the directory holding
    its children. We honour both intuitions:

    - ``is_ignored(child_rel, is_dir=True)`` catches a literal ``Archive/``
      pattern even on a leaf page (where ``prune_dir`` would fail because
      there are no probe descendants).
    - ``prune_dir`` adds the stricter "every descendant provably ignored"
      guarantee used for patterns like ``**/Archive/``.
    """
    pruned: set[PurePosixPath] = set()
    for pr in rels.values():
        child = Path(pr.child_rel)
        if matcher.is_ignored(child, is_dir=True) or matcher.prune_dir(child):
            pruned.add(pr.child_rel)
    return pruned


def _classify_page(
    pr: _PageRel,
    matcher: MddIgnore,
    pruned_dirs: set[PurePosixPath],
) -> tuple[str, str | None]:
    """Classify a single page against the matcher.

    Returns ``(verdict, skip_path)`` where verdict is one of:
    ``"keep"`` — the page passes the filter.
    ``"prune-root"`` — the page IS an ignored-subtree root; ``skip_path``
      is the subtree rel-path with a trailing ``/``.
    ``"prune-descendant"`` — the page lives under an already-recorded
      prune root; ``skip_path`` is ``None`` (no extra summary entry).
    ``"file-skip"`` — the page's ``.md`` itself matches a pattern;
      ``skip_path`` is the rel-path.
    """
    if pr.child_rel in pruned_dirs:
        return "prune-root", str(pr.child_rel) + "/"
    if _ancestor_in(pr.md_rel, pruned_dirs) is not None:
        return "prune-descendant", None
    if matcher.is_ignored(Path(pr.md_rel), is_dir=False):
        return "file-skip", str(pr.md_rel)
    return "keep", None


def filter_desired(
    desired: dict[str, DesiredPage],
    tracked_ids: set[str],
    matcher: MddIgnore,
    client: ConfluenceClient,
) -> tuple[dict[str, DesiredPage], list[str]]:
    """Drop pages from *desired* that the matcher would ignore.

    Already-tracked pages (``page_id in tracked_ids``) are never dropped,
    matching git's "ignore-on-pull only, never delete" contract.

    Returns a ``(filtered_desired, skipped_paths)`` pair. ``skipped_paths``
    is a list of POSIX rel-path strings — pruned directories carry a
    trailing ``/`` so the per-sync summary can distinguish them from
    per-page skips.
    """
    rels = build_page_rel_paths(desired, client)
    if not rels:
        return desired, []
    pruned_dirs = _compute_pruned_dirs(rels, matcher)

    filtered: dict[str, DesiredPage] = {}
    skipped_paths: list[str] = []
    seen_pruned: set[PurePosixPath] = set()
    for page_id, page in desired.items():
        pr = rels.get(page_id)
        if page_id in tracked_ids or pr is None:
            filtered[page_id] = page
            continue
        verdict, skip_path = _classify_page(pr, matcher, pruned_dirs)
        if verdict == "keep":
            filtered[page_id] = page
        elif verdict == "prune-root" and pr.child_rel not in seen_pruned:
            seen_pruned.add(pr.child_rel)
            if skip_path is not None:
                skipped_paths.append(skip_path)
        elif verdict == "file-skip" and skip_path is not None:
            skipped_paths.append(skip_path)
    return filtered, skipped_paths


def _ancestor_in(rel: PurePosixPath, candidates: set[PurePosixPath]) -> PurePosixPath | None:
    """Return the first member of *candidates* that is an ancestor of *rel*, else None."""
    for parent in rel.parents:
        if parent in candidates:
            return parent
    return None
