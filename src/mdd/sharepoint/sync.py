"""sync.py — sync-root resolution, site discovery, and bidirectional sync."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from mdd.convert import CorruptSourceError
from mdd.mirror.errors import MirrorEnsureError
from mdd.mirror.orchestrator import bootstrap_worktree
from mdd.mirror.protocol import MirrorTarget
from mdd.mirror.registry import default_backend
from mdd.sharepoint.apply import SyncRunSummary, git_commit
from mdd.sharepoint.diff import classify_pair, read_sync_state

# Re-exported for test-patch compatibility: tests patch
# ``mdd.sharepoint.sync.apply_pair`` (see tests/sharepoint/test_bidirectional_sync.py).
# The implementation now lives in mdd.sharepoint.dispatch; keep this binding so
# the existing patch target still resolves. print_dry_run_plan is re-imported
# alongside it because sync_folder calls it directly. The underscore prefixes
# were dropped on the moved symbols to satisfy basedpyright's reportPrivateUsage
# on the cross-module import.
from mdd.sharepoint.dispatch import apply_pair, print_dry_run_plan
from mdd.sharepoint.mapping import load_mapping, repo_name
from mdd.utils.blacklist import check_sharepoint
from mdd.utils.git import is_git_repo
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from mdd.mirror.protocol import MirrorBackend
    from mdd.sharepoint.models import SharepointCliConfig
    from mdd.utils.mddignore import MddIgnore


log = get_logger(__name__)


class SyncRootMissing(Exception):
    """Raised when no OneDrive sync root can be found."""


@dataclass
class SiteEntry:
    """A single syncable unit found under the OneDrive sync root."""

    path: Path
    display_name: str
    is_library_root: bool
    derived_site_name: str  # display_name with " - Documents" suffix stripped if is_library_root


_DOCUMENTS_SUFFIX = " - Documents"


def resolve_sync_root(config: SharepointCliConfig | None = None) -> Path:
    """Return the OneDrive sync root directory.

    Resolution order:
      1. ``config.sharepoint.sync_root`` if provided and exists.
      2. The single ``~/Library/CloudStorage/OneDrive-SharedLibraries-*``
         directory, if exactly one exists. Tenant names are site-specific,
         so this is discovered rather than hard-coded; with more than one
         tenant synced the choice is ambiguous and the config must say.
      3. Raise :class:`SyncRootMissing`.
    """
    if config is not None and config.sharepoint is not None:
        sync_root_raw = config.sharepoint.sync_root
        if sync_root_raw is not None:
            candidate = Path(sync_root_raw).expanduser()
            if candidate.exists():
                return candidate

    cloud = Path.home() / "Library" / "CloudStorage"
    shared = sorted(p for p in cloud.glob("OneDrive-SharedLibraries-*") if p.is_dir())
    if len(shared) == 1:
        return shared[0]
    if len(shared) > 1:
        names = ", ".join(p.name for p in shared)
        raise SyncRootMissing(
            f"Multiple OneDrive shared-library roots found ({names}). "
            "Set `sharepoint.sync_root` in your config to pick one."
        )

    raise SyncRootMissing(
        "OneDrive sync root not found. Expected a directory matching "
        "~/Library/CloudStorage/OneDrive-SharedLibraries-*, or "
        "`sharepoint.sync_root` in your config. "
        "Note: mdd sharepoint currently supports macOS only. "
        "Sync a SharePoint site via OneDrive and try again."
    )


def list_sites(sync_root: Path) -> list[SiteEntry]:
    """Return one :class:`SiteEntry` per immediate child directory of *sync_root*.

    Skips:
    - Non-directory entries.
    - Names starting with ``.`` or ``_``.
    """
    entries: list[SiteEntry] = []
    for child in sorted(sync_root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith((".", "_")):
            continue
        if name.endswith(_DOCUMENTS_SUFFIX):
            derived = name[: -len(_DOCUMENTS_SUFFIX)]
            entries.append(
                SiteEntry(
                    path=child,
                    display_name=name,
                    is_library_root=True,
                    derived_site_name=derived,
                )
            )
        else:
            entries.append(
                SiteEntry(
                    path=child,
                    display_name=name,
                    is_library_root=False,
                    derived_site_name=name,
                )
            )
    return entries


# ---------------------------------------------------------------------------
# Bidirectional sync
# ---------------------------------------------------------------------------

_DIRTY_TREE_MESSAGE = (
    "Mirror has uncommitted changes. Commit, stash, or discard before running sync."
)

# Office extensions handled by the bidirectional sync loop
_OFFICE_EXTENSIONS: frozenset[str] = frozenset({".docx", ".pptx"})


class SyncError(Exception):
    """Raised when sync cannot proceed (e.g. dirty git tree, site not found)."""


def _is_real_filename(name: str) -> bool:
    """True if *name* is a regular candidate (not a dotfile, not a Word lock)."""
    return not name.startswith((".", "~$"))


@dataclass
class _WalkStats:
    """Accounting bucket for an ignore-aware walk.

    Tracks pruned directories and per-file skips so the caller can fold
    them into the per-sync ``skipped_ignored`` counter without re-walking
    the source tree.
    """

    pruned_dirs: list[Path] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)


def _maybe_prune_dir(
    child: Path,
    rel_root: Path,
    matcher: MddIgnore | None,
    stats: _WalkStats | None,
) -> bool:
    """Return True iff *child* (a directory) was pruned by *matcher*.

    Records the pruned path on *stats* when supplied.
    """
    if matcher is None:
        return False
    rel = child.relative_to(rel_root)
    if not matcher.prune_dir(rel):
        return False
    if stats is not None:
        stats.pruned_dirs.append(rel)
    return True


def _maybe_skip_file(
    child: Path,
    rel_root: Path,
    matcher: MddIgnore | None,
    stats: _WalkStats | None,
) -> bool:
    """Return True iff *child* (a file) is matched and should be skipped."""
    if matcher is None:
        return False
    rel = child.relative_to(rel_root)
    if not matcher.is_ignored(rel, is_dir=False):
        return False
    if stats is not None:
        stats.skipped_files.append(rel)
    return True


def _classify_walk_child(
    child: Path,
    rel_root: Path,
    matcher: MddIgnore | None,
    stats: _WalkStats | None,
    *,
    stack: list[Path],
    collected: list[Path],
) -> None:
    """Route one walk entry: ignore non-files, push surviving dirs, keep files.

    Kept as a top-level helper so :func:`_walk_real_files` stays inside the
    cognitive-complexity ceiling.
    """
    if not _is_real_filename(child.name):
        return
    if child.is_dir():
        if not _maybe_prune_dir(child, rel_root, matcher, stats):
            stack.append(child)
        return
    if child.is_file() and not _maybe_skip_file(child, rel_root, matcher, stats):
        collected.append(child)


def _walk_real_files(
    root: Path,
    *,
    matcher: MddIgnore | None = None,
    rel_base: Path | None = None,
    stats: _WalkStats | None = None,
) -> list[Path]:
    """Return sorted real files under *root*, honouring the ``.mddignore`` matcher.

    Dotfiles and Word locks are skipped (matches the prior ``rglob``
    behaviour). When *matcher* is supplied:

    - Subdirectories whose every descendant would be ignored are pruned
      entirely (``matcher.prune_dir``), and their paths (relative to
      *rel_base* if given, else *root*) are appended to ``stats.pruned_dirs``.
    - Files matched by ``matcher.is_ignored`` are dropped from the result
      and recorded in ``stats.skipped_files``.
    """
    if not root.exists():
        return []
    rel_root = rel_base if rel_base is not None else root
    collected: list[Path] = []
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError, PermissionError:
            continue
        for child in children:
            _classify_walk_child(child, rel_root, matcher, stats, stack=stack, collected=collected)
    collected.sort()
    return collected


def _walk_for_pairs(
    source_root: Path,
    output_root: Path,
    *,
    matcher: MddIgnore | None = None,
    stats: _WalkStats | None = None,
) -> list[tuple[Path, Path]]:
    """Walk *source_root* / *output_root* and return ``(office, md)`` path pairs.

    - For each ``.docx`` / ``.pptx`` in *source_root*, the md sibling is
      ``output_root / <rel-path> / (office.name + ".md")``. The md path is
      returned even if it does not exist yet — :func:`classify_pair` decides the
      first-sync action via ``.exists()`` checks.
    - For each ``.docx.md`` / ``.pptx.md`` in *output_root* whose corresponding
      office file is missing in *source_root*, the office path is returned as
      the *intended* location in the source tree (md-only first sync).

    Word lock files (``~$Foo.docx``) and dotfiles are skipped.

    Returns pairs sorted by the office path.

    *matcher* — when supplied, prunes ignored subtrees in
    *source_root* before listing and drops files matched by ``is_ignored``.
    The matcher is applied to **source_root only**; existing destination
    state is honoured the same way ``git`` honours already-tracked files
    that newly match ``.gitignore`` (we never disturb existing output).
    """
    pairs: list[tuple[Path, Path]] = []
    seen_md: set[Path] = set()

    # Office files in source → md sibling in output. The matcher prunes
    # source-side subtrees here, which is where the 12 → ~5 GB saving
    # actually shows up: ``Archive/`` never gets listed.
    for fp in _walk_real_files(source_root, matcher=matcher, stats=stats):
        if fp.suffix.lower() in _OFFICE_EXTENSIONS:
            rel = fp.relative_to(source_root)
            md_in_output = output_root / rel.parent / (fp.name + ".md")
            seen_md.add(md_in_output)
            pairs.append((fp, md_in_output))

    # Orphaned .md in output (no office sibling in source). The matcher
    # never touches output_root — already-synced state is the user's to
    # clean up.
    for fp in _walk_real_files(output_root):
        if fp.suffix.lower() != ".md" or fp in seen_md:
            continue
        stem = fp.stem  # e.g. "Foo.docx"
        if Path(stem).suffix.lower() not in _OFFICE_EXTENSIONS:
            continue  # plain notes.md — not a sync pair
        rel = fp.relative_to(output_root)
        office_in_source = source_root / rel.parent / stem
        if not office_in_source.exists():
            pairs.append((office_in_source, fp))

    pairs.sort(key=lambda pair: pair[0])
    return pairs


def _check_dirty(output_dir: Path) -> None:
    """Raise SyncError if the output directory has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(output_dir),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        # git not available — skip dirty check
        return
    if result.stdout.strip():
        raise SyncError(_DIRTY_TREE_MESSAGE)


def derive_site_name(folder_name: str) -> str:
    """Derive the canonical site name from a local folder name."""
    if folder_name.endswith(_DOCUMENTS_SUFFIX):
        return folder_name[: -len(_DOCUMENTS_SUFFIX)]
    return folder_name


def _bootstrap_repo(
    output_dir: Path, target: MirrorTarget, backend: MirrorBackend, summary: SyncRunSummary
) -> bool:
    """Initialize *output_dir* as a git repo pointing at the backend's remote.

    Derives the clone URL via the :class:`~mdd.mirror.protocol.MirrorBackend`
    seam and runs the generic bootstrap. Returns True on success, False on
    failure (also recorded in ``summary.errors``). A backend with no remote
    (``local``) has nothing to bootstrap against, which is a success — the
    mirror simply stays local.
    """
    remote_url = backend.resolve_remote(target)
    if remote_url is None:
        return True
    ok, err = bootstrap_worktree(output_dir, remote_url)
    if not ok:
        assert err is not None  # noqa: S101  # invariant: bootstrap returns an error message on failure
        summary.errors.append(err)
        return False
    return True


def _ensure_remote_for_push(
    target: MirrorTarget, backend: MirrorBackend, summary: SyncRunSummary
) -> bool:
    """Verify-or-create the remote project via the backend seam.

    Returns True on success or soft-skip; False if the create attempt
    itself failed (recorded in ``summary.errors``).
    """
    try:
        outcome = backend.ensure_remote(target)
    except MirrorEnsureError as exc:
        log.error(str(exc))
        summary.errors.append(str(exc))
        return False

    if outcome.status == "unreachable":
        log.warning(
            "Skipping mirror repo ensure (%s); push will retry if reachable.",
            outcome.reason,
        )
    elif outcome.status == "created":
        log.info("Created mirror repo: %s", outcome.remote_url or target.key)
    return True


def _run_prune_ignored(
    dest_root: Path,
    matcher: MddIgnore | None,
    summary: SyncRunSummary,
    *,
    dry_run: bool,
) -> None:
    """Apply the ``--prune-ignored`` pre-pass against *dest_root*.

    Walks the mirror tree once, deletes (or — under ``dry_run`` — logs)
    every file the matcher marks ignored, and updates the summary
    counters. A missing matcher or an empty matcher is a no-op.
    """
    if matcher is None:
        return
    summary.pruned_ignored_dry_run = dry_run
    for path in matcher.walk_prunable(dest_root):
        rel = path.relative_to(dest_root).as_posix()
        if dry_run:
            log.info("would prune (ignored, dry-run): %s", rel)
        else:
            log.info("pruned (ignored): %s", rel)
            try:
                path.unlink()
            except OSError as exc:
                summary.errors.append(f"prune {rel}: {exc}")
                continue
        summary.pruned_ignored += 1
        summary.pruned_ignored_paths.append(rel)


def sync_folder(  # noqa: PLR0913
    local_path: Path,
    *,
    output_dir: Path,
    dry_run: bool = False,
    push: bool = False,
    backup: bool = False,
    head: int | None = None,
    message: str | None = None,
    read_only: bool = False,
    mirror_target: MirrorTarget | None = None,
    matcher: MddIgnore | None = None,
    prune_ignored: bool = False,
) -> SyncRunSummary:
    """Sync an arbitrary local OneDrive folder bidirectionally.

    Args:
        local_path: Path to the local OneDrive (source) folder. Office files live
            here; the markdown mirror lives under *output_dir*.
        output_dir: Root of the Markdown mirror (a git clone, typically). All
            ``.md`` files are read from and written to this tree; the office
            tree under *local_path* is the source of truth for ``.docx`` /
            ``.pptx`` files.
        dry_run: If True, print the plan and return without writing anything.
        push: If True, push after the commit via the mirror backend. When
            *output_dir* is not yet a git repo and *mirror_target* is
            supplied, sync bootstraps the repo (``git init`` + ``origin``) and
            ensures the remote project exists before pushing.
        backup: If True, back up office files before overwriting.
        head: If set, limit to the first N pairs (alphabetical order).
        message: Custom git commit message (default: auto-generated).
        read_only: If True, suppress every mirror → OneDrive/SharePoint write
            step. The local mirror and the mirror push (when ``push`` is set)
            are still allowed.
        mirror_target: Identifies the remote to bootstrap a missing git repo
            against on ``--push``; the backend derives the concrete URL.
            ``sync-site`` builds this from the mapping; ``sync-folder``
            callers without a site identity pass ``None`` and lose the
            bootstrap convenience.

    Returns:
        A :class:`~mdd.sharepoint.apply.SyncRunSummary` with counters.

    Raises:
        SyncError: If the output directory has uncommitted changes or the path is invalid.
    """
    if not local_path.exists():
        raise SyncError(f"Path does not exist: {local_path}")
    if not local_path.is_dir():
        raise SyncError(f"Path is not a directory: {local_path}")

    site_name = derive_site_name(local_path.name)
    check_sharepoint(site_name)

    _check_dirty(output_dir)

    summary = SyncRunSummary()
    # prune-ignored runs BEFORE the normal sync walk so the
    # ``would prune (ignored, dry-run)`` lines still show up under
    # ``--dry-run``. Summary counters are surfaced even when no work was
    # done — empty matcher = empty walk = zero counter, no surprise.
    if prune_ignored:
        _run_prune_ignored(output_dir, matcher, summary, dry_run=dry_run)

    walk_stats = _WalkStats()
    pairs = _walk_for_pairs(local_path, output_dir, matcher=matcher, stats=walk_stats)
    if head is not None:
        pairs = pairs[:head]

    # Roll the source-side ``.mddignore`` skips into the summary so the
    # caller can surface a "N skipped (ignored)" line. Pruned directories
    # are counted once each rather than by descendant count; per-file
    # skips are counted exactly. Done before the dry-run branch so
    # dry-run reports the matcher's effect.
    summary.skipped_ignored = len(walk_stats.skipped_files) + len(walk_stats.pruned_dirs)
    summary.skipped_ignored_paths = [str(p) for p in walk_stats.skipped_files]
    summary.skipped_ignored_paths.extend(str(p) + "/" for p in walk_stats.pruned_dirs)

    if dry_run:
        print_dry_run_plan(pairs, read_only=read_only)
        return summary

    for docx_path, md_path in pairs:
        sync_state = read_sync_state(md_path)
        action = classify_pair(docx_path, md_path, sync_state=sync_state)

        try:
            apply_pair(
                action=action,
                docx_path=docx_path,
                md_path=md_path,
                output_dir=output_dir,
                backup=backup,
                read_only=read_only,
                summary=summary,
                sync_state=sync_state,
            )
        except CorruptSourceError:
            # Empty or non-Office-ZIP source files are a permanent,
            # uninteresting condition — count them separately so they don't
            # drown out genuine errors in the run summary.
            name = docx_path.name if docx_path.exists() else md_path.name
            summary.skipped_corrupt += 1
            summary.skipped_corrupt_paths.append(name)
            log.info("[SKIP] %s: corrupt or empty source", name)
        except Exception as exc:
            name = docx_path.name if docx_path.exists() else md_path.name
            err_msg = f"{name}: {exc}"
            summary.errors.append(err_msg)
            log.error(err_msg)

    _finalize_sync_folder(
        output_dir=output_dir,
        site_name=site_name,
        summary=summary,
        push=push,
        message=message,
        mirror_target=mirror_target,
    )
    return summary


def _finalize_sync_folder(
    *,
    output_dir: Path,
    site_name: str,
    summary: SyncRunSummary,
    push: bool,
    message: str | None,
    mirror_target: MirrorTarget | None,
) -> None:
    """Bootstrap (on --push), commit, and optionally push the mirror.

    SharePoint keeps its own summary-driven :func:`git_commit` (which
    no-ops outside a git repo, so ``sync-folder`` without ``--push``
    stays quiet) and routes the provider-specific bootstrap / ensure /
    push through the :class:`~mdd.mirror.protocol.MirrorBackend` seam.
    """
    backend = default_backend()

    # Cold-start bootstrap: if --push and the mirror is not yet a git repo,
    # initialize it now so the commit + push below have somewhere to land.
    needs_init = push and not is_git_repo(output_dir)
    if (
        needs_init
        and mirror_target is not None
        and not _bootstrap_repo(output_dir, mirror_target, backend, summary)
    ):
        return

    # Commit if anything changed. git_commit no-ops outside a git repo, so the
    # ``sync-folder`` (no --push, no git init) path is safe too.
    if summary.has_changes():
        try:
            _ = git_commit(output_dir, summary, site_name)
        except Exception as exc:
            log.warning("git commit failed: %s", exc)

    if not (push and is_git_repo(output_dir)):
        return

    if mirror_target is not None and not _ensure_remote_for_push(mirror_target, backend, summary):
        return

    backend.push(output_dir, message=message)


def _mirror_target_for_site(site_name: str, mapping_path: Path | None) -> MirrorTarget:
    """Return the mirror target for *site_name*.

    The key is the mapped repo name; the backend owns the group/host
    prefix, so this stays provider-agnostic.
    """
    return MirrorTarget(kind="sharepoint", key=repo_name(site_name, load_mapping(mapping_path)))


def sync_site(  # noqa: PLR0913
    site_name: str,
    *,
    config: SharepointCliConfig | None = None,
    output_dir: Path,
    dry_run: bool = False,
    push: bool = False,
    backup: bool = False,
    head: int | None = None,
    message: str | None = None,
    read_only: bool = False,
    mapping_path: Path | None = None,
    matcher: MddIgnore | None = None,
    prune_ignored: bool = False,
) -> SyncRunSummary:
    """Sync a named SharePoint site (resolved via OneDrive) bidirectionally.

    This is the high-level entry point for ``mdd sharepoint sync site``.

    Args:
        site_name: The canonical (derived) site name.
        config: Optional config object with ``sharepoint.sync_root`` etc.
        output_dir: Root of the Markdown mirror.
        dry_run: Print plan without writing.
        push: Push after commit.
        backup: Back up office files before overwriting.
        head: Limit to first N pairs.
        message: Custom commit message.
        read_only: If True, suppress every mirror → OneDrive/SharePoint write
            step.
        mapping_path: Optional path to ``sharepoint-mapping.yaml`` used to
            derive the mirror repo name for the cold-start bootstrap on
            ``--push``. Default: standard mapping search.

    Raises:
        SyncError: If the site cannot be found or the tree is dirty.
    """
    sync_root = resolve_sync_root(config)
    sites = list_sites(sync_root)

    site_entry: SiteEntry | None = None
    for entry in sites:
        if entry.derived_site_name == site_name:
            site_entry = entry
            break

    if site_entry is None:
        available = [e.derived_site_name for e in sites]
        raise SyncError(
            f"Site {site_name!r} not found in sync root {sync_root}. Available sites: {available}"
        )

    check_sharepoint(site_entry.derived_site_name)
    _check_dirty(output_dir)

    mirror_target = _mirror_target_for_site(site_entry.derived_site_name, mapping_path)

    return sync_folder(
        site_entry.path,
        output_dir=output_dir,
        dry_run=dry_run,
        push=push,
        backup=backup,
        head=head,
        message=message,
        read_only=read_only,
        mirror_target=mirror_target,
        matcher=matcher,
        prune_ignored=prune_ignored,
    )
