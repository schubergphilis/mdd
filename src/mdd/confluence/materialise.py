"""Per-page materialisation helpers for ``move-page``.

When ``mdd confluence move-page`` lands a file under a new parent
whose ancestor chain is not yet fully present in the local mirror,
the orchestrator (:mod:`mdd.confluence.mutate`) walks the chain and
calls these helpers for each missing link before doing the ``git mv``:

- :func:`pull_single_page` exports one ancestor page from Confluence
  into its expected directory as ``_index.md`` — reusing the same
  pipeline :mod:`mdd.confluence.sync.pull` uses for content edits.
- :func:`promote_flat_to_dir` converts a flat ``Title.md`` (a page
  that previously had no children locally) into ``Title/_index.md``
  so that a child can live inside it.  The attachments directory is
  carried along.

These helpers are written to be callable from the imperative mutate
path without rebuilding a full :class:`MirrorState`.

Partial materialisation is acceptable on failure: the
Confluence-side move is the source of truth and is not rolled back;
``sync-space`` reconciles any half-built local state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mdd.confluence.apply import ApplyError, git_mv
from mdd.confluence.export import export_page
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.confluence.client import ConfluenceClient

log = get_logger(__name__)

# Conventional filename for the "directory-shaped" representation of a
# page that has at least one child page.  Lives here, not in
# :mod:`mdd.confluence.paths`, because today it is only produced by the
# move-page materialisation path; sync still uses the flat+sibling
# layout for newly-pulled trees.
INDEX_BASENAME = "_index.md"


@dataclass(frozen=True)
class PullResult:
    """Outcome of a :func:`pull_single_page` call.

    ``written_path`` is the on-disk path of the newly materialised
    ``_index.md`` (or whatever filename ``export_page`` chose — it
    sanitises the title); callers that need a specific shape MUST
    rename after the export completes.
    """

    page_id: str
    written_path: Path


def pull_single_page(
    client: ConfluenceClient,
    page_id: str,
    target_dir: Path,
) -> PullResult:
    """Export one Confluence page into ``target_dir`` as ``_index.md``.

    Reuses the same :func:`mdd.confluence.export.export_page` pipeline
    that ``sync-space`` uses for new / content-edit events.  After the
    pipeline writes ``target_dir/<sanitized-title>.md``, this helper
    renames the file to ``target_dir/_index.md`` so the directory
    represents an ancestor page in the mirror tree.

    Attachments are fetched the same way sync does (the export pipeline
    handles them).  The caller is responsible for staging the resulting
    files via ``git add`` — they land untracked.

    Raises :class:`mdd.confluence.client.ConfluenceError` on API
    failures, :class:`OSError` on filesystem failures.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    written = export_page(client, page_id, target_dir)
    index_path = target_dir / INDEX_BASENAME
    if written != index_path:
        # ``export_page`` writes ``<safe-title>.md``; rename onto
        # ``_index.md`` so the directory represents the page.  We use
        # a plain rename rather than ``git mv`` because the file was
        # just written and is not yet tracked.
        written.replace(index_path)
    return PullResult(page_id=page_id, written_path=index_path)


def promote_flat_to_dir(
    flat_md_path: Path,
    expected_dir: Path,
    repo_dir: Path,
) -> Path:
    """Promote ``flat_md_path`` to ``expected_dir/_index.md`` via ``git mv``.

    Used when an ancestor page is present in the mirror as a flat
    ``Title.md`` (no children directory yet) and now needs to acquire
    a child.  The post-state is ``Title/_index.md``.

    The page's attachments directory (``<stem>-attachments/``) is moved
    alongside the page when present.  Both moves go through
    :func:`mdd.confluence.apply.git_mv` so the rename stays in git
    history.

    Raises :class:`mdd.confluence.apply.ApplyError` when the underlying
    ``git mv`` fails; the caller turns that into a recovery hint.
    """
    expected_dir.mkdir(parents=True, exist_ok=True)
    new_index_path = expected_dir / INDEX_BASENAME
    git_mv(flat_md_path, new_index_path, repo_dir)

    att_old = flat_md_path.parent / f"{flat_md_path.stem}-attachments"
    if att_old.exists():
        att_new = expected_dir / f"{expected_dir.name}-attachments"
        try:
            git_mv(att_old, att_new, repo_dir)
        except ApplyError as exc:
            # Don't fail the whole move for an attachments-dir hiccup;
            # the next ``sync-space`` will reconcile.
            log.warning(
                "promote: attachments-dir move %s -> %s failed: %s",
                att_old,
                att_new,
                exc,
            )
    return new_index_path
