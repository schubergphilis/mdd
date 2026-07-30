"""Conflict recording, metadata refresh, commit, push, mirror state build.

Commit + push is generic across mirror sources, so it delegates to
:mod:`mdd.mirror.orchestrator` driven by the registry's default
:class:`~mdd.mirror.protocol.MirrorBackend`. The Confluence-specific bits
(conflict recording, frontmatter metadata refresh, mirror-state build,
structured ``SyncSummary`` commit message) stay here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mdd.confluence.apply import ApplyError
from mdd.confluence.frontmatter import read as read_frontmatter
from mdd.confluence.frontmatter import write as write_frontmatter
from mdd.confluence.state import DuplicatePageIdError, build_mirror_state
from mdd.confluence.sync_diff import EventKind, SyncEvent
from mdd.mirror.errors import MirrorEnsureError, MirrorError, MirrorPushError
from mdd.mirror.orchestrator import commit_and_push
from mdd.mirror.protocol import MirrorTarget
from mdd.mirror.registry import default_backend
from mdd.utils.git import is_git_repo as _is_git_repo
from mdd.utils.logging import get_logger

from ._helpers import pin_mtime_to_exported_at
from .renames import resolve_path_after_rename

if TYPE_CHECKING:
    from pathlib import Path

    from ._types import SyncSummary

log = get_logger(__name__)


def is_git_repo(output_dir: Path) -> bool:
    """Return True if *output_dir* is a git working tree.

    Thin re-export of :func:`mdd.utils.git.is_git_repo`, kept because
    callers and test mocks import it from this module (issue #132).
    """
    return _is_git_repo(output_dir)


def record_conflicts(events: list[SyncEvent], summary: SyncSummary) -> None:
    for event in events:
        if event.kind == EventKind.CONFLICT:
            path_str = event.current_path or event.page_id
            summary.conflicts.append(path_str)
            log.warning("conflict: %s skipped (local + remote both edited)", path_str)


def refresh_metadata(
    events: list[SyncEvent],
    mirror: Any,
    summary: SyncSummary,  # pyright: ignore[reportAny]  # noqa: ARG001
) -> None:
    for event in events:
        if event.kind != EventKind.METADATA_ONLY:
            continue
        if event.desired is None or event.current_path is None:
            continue
        page_id = event.page_id
        current_path = resolve_path_after_rename(mirror, page_id, event.current_path)
        desired_page = event.desired
        try:
            fm, body = read_frontmatter(current_path)
            conf_raw: Any = fm.get("confluence")  # pyright: ignore[reportAny]
            if isinstance(conf_raw, dict):
                conf: dict[str, Any] = conf_raw  # pyright: ignore[reportUnknownVariableType]
                conf["labels"] = desired_page.labels
                conf["status"] = desired_page.status
                write_frontmatter(current_path, fm, body)
                pin_mtime_to_exported_at(current_path, fm)
        except (OSError, Exception) as exc:
            log.warning("metadata refresh %s: %s", page_id, exc)


def finalize_commit_and_push(
    output_dir: Path,
    summary: SyncSummary,
    space_key: str,
    message: str | None,
    *,
    push: bool,
) -> None:
    """Commit any pending changes and optionally push to the mirror remote.

    Routes through the :class:`~mdd.mirror.protocol.MirrorBackend` seam:
    builds the Confluence-specific commit message from
    *summary*, hands a ``MirrorTarget("confluence", space_key)`` to the
    generic orchestrator and the registry's default backend (which
    derives the remote path), and threads results back onto *summary*
    (``committed``, ``commit_sha``, ``failures``).
    """
    commit_msg = summary.format_commit_message(space_key, message_override=message)
    target = MirrorTarget(kind="confluence", key=space_key) if push else None
    try:
        result = commit_and_push(
            output_dir,
            commit_message=commit_msg,
            backend=default_backend(),
            target=target,
            push=push,
        )
    except MirrorError as exc:
        # Cold-start "not a git repo, can't bootstrap" — preserves the
        # historic "commit: ..." prefix tested against in
        # tests/commands/test_confluence_sync.py.
        log.error("commit: %s", exc)
        summary.failures.append(f"commit: {exc}")
        return

    summary.committed = result.committed
    summary.commit_sha = result.commit_sha
    summary.failures.extend(result.errors)


# Backwards-compatible aliases used by sync/__init__.py and test mocks.
def initialize_repo(output_dir: Path, space_key: str, summary: SyncSummary) -> bool:  # noqa: ARG001
    """Deprecated: the bootstrap step lives inside :func:`finalize_commit_and_push`.

    Retained as a thin no-op + always-True return so any external mocks
    that patch this name during testing keep working. Issue #132 folded
    the ``git init`` + ``remote add origin`` step into the workdir
    orchestrator's cold-start path.
    """
    return True


def commit_changes(
    output_dir: Path, summary: SyncSummary, space_key: str, message: str | None
) -> None:
    """Backwards-compatible wrapper for the pre-issue-#132 entry point."""
    finalize_commit_and_push(output_dir, summary, space_key, message, push=False)


def push_to_gitlab(output_dir: Path, summary: SyncSummary, *, space_key: str | None = None) -> None:
    """Backwards-compatible wrapper for the pre-issue-#132 entry point.

    Pre-#132 callers commit first, then call this. To preserve the same
    visible behaviour without re-committing, this ensures the remote
    project and pushes via the :class:`~mdd.mirror.protocol.MirrorBackend`
    seam, skipping the commit step.
    """
    backend = default_backend()
    if space_key is not None:
        try:
            outcome = backend.ensure_remote(MirrorTarget(kind="confluence", key=space_key))
        except MirrorEnsureError as exc:
            log.error(str(exc))
            summary.failures.append(str(exc))
            return
        if outcome.status == "unreachable":
            log.warning(
                "Skipping mirror repo ensure (%s); push will retry if reachable.",
                outcome.reason,
            )
        elif outcome.status == "created":
            log.info("Created mirror repo: %s", outcome.remote_url or space_key)

    try:
        backend.push(output_dir)
    except (MirrorPushError, RuntimeError) as exc:
        log.error("push: %s", exc)
        summary.failures.append(f"push: {exc}")
        return
    log.info("Pushed to mirror remote.")


def build_mirror_or_raise(output_dir: Path, summary: SyncSummary) -> Any:  # pyright: ignore[reportAny]
    """Build the mirror state, print stats, and raise ApplyError on duplicates."""
    try:
        mirror = build_mirror_state(output_dir)
    except DuplicatePageIdError as exc:
        raise ApplyError(str(exc)) from exc
    log.info(
        "Mirror: %d tracked, %d untracked (publish candidates), "
        "%d manually-managed, %d attachment-derived.",
        len(mirror.tracked),
        len(mirror.untracked),
        len(mirror.manual),
        len(mirror.attachment_derived),
    )
    summary.skipped_manual = len(mirror.manual)
    summary.skipped_attachment_derived = len(mirror.attachment_derived)
    if mirror.manual:
        manual_rel = [str(p.relative_to(output_dir)) for p in mirror.manual[:3]]
        more = len(mirror.manual) - len(manual_rel)
        suffix = f" ... and {more} more" if more > 0 else ""
        log.info(
            "Manually-managed files (sync leaves them untouched): %s%s",
            ", ".join(manual_rel),
            suffix,
        )
    return mirror
