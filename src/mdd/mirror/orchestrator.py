"""Generic commit-and-push orchestration for the sync engines.

The provider-agnostic part of ending a sync run — refuse-or-bootstrap
the work-tree, commit, and (optionally) ensure-the-remote + push —
driven by a :class:`~mdd.mirror.protocol.MirrorBackend`. The
provider-specific knowledge (remote URL derivation, project auto-create,
push guard, reachability) lives behind the backend seam.

The lower-level :func:`git_commit` is exposed for callers that need just
the commit step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mdd.mirror.errors import MirrorEnsureError, MirrorError, MirrorPushError
from mdd.utils.git import GitError, is_git_repo, run_git, run_git_lenient
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.mirror.protocol import MirrorBackend, MirrorTarget

log = get_logger(__name__)

__all__ = [
    "CommitAndPushResult",
    "bootstrap_worktree",
    "commit_and_push",
    "git_commit",
]


def git_commit(repo_dir: Path, message: str) -> tuple[bool, str]:
    """Stage everything under *repo_dir* and commit with *message*.

    Returns ``(committed, sha)`` where ``committed`` is True if a commit
    was created and ``sha`` is the resulting HEAD (empty string if no
    commit was created or the rev-parse step failed).

    "Nothing to commit" is treated as a non-error: returns
    ``(False, "")`` rather than raising. Any other git failure raises
    :class:`~mdd.mirror.errors.MirrorError`.
    """
    # Pre-check: if porcelain is empty, nothing to do. Staging an empty
    # tree is cheap but wastes a subprocess.
    porcelain = run_git_lenient(["status", "--porcelain"], repo_dir, timeout=10)
    if porcelain.returncode != 0 or not porcelain.stdout.strip():
        return False, ""

    # `--ignore-errors` keeps `add` going past files it can't read (e.g. a
    # file quarantined mid-sync by endpoint protection, which raises EPERM
    # on open()) instead of aborting the whole stage. Git still exits
    # non-zero when it skipped something, so this uses the lenient runner
    # and defers the pass/fail call to whether anything actually staged.
    add_result = run_git_lenient(["add", "-A", "--ignore-errors", "--", "."], repo_dir)
    if add_result.returncode != 0:
        log.warning(
            "git add skipped some files (unreadable?): %s",
            add_result.stderr.strip() or add_result.stdout.strip(),
        )

    # Confirm something is actually staged after `add -A` (e.g. only
    # ignored files in porcelain output would stage nothing).
    staged = run_git_lenient(["diff", "--cached", "--stat"], repo_dir, timeout=10)
    if not staged.stdout.strip():
        if add_result.returncode != 0:
            raise MirrorError(
                f"git add failed and nothing was staged (exit {add_result.returncode}): "
                f"{add_result.stderr.strip() or add_result.stdout.strip()}"
            )
        return False, ""

    commit_result = run_git_lenient(["commit", "-m", message], repo_dir, timeout=60)
    if commit_result.returncode != 0:
        combined = commit_result.stdout + "\n" + commit_result.stderr
        if "nothing to commit" in combined:
            return False, ""
        raise MirrorError(
            f"git commit failed (exit {commit_result.returncode}): "
            f"{commit_result.stderr.strip() or commit_result.stdout.strip()}"
        )

    head = run_git_lenient(["rev-parse", "HEAD"], repo_dir, timeout=10)
    sha = head.stdout.strip() if head.returncode == 0 else ""
    return True, sha


@dataclass
class CommitAndPushResult:
    """Outcome of :func:`commit_and_push`."""

    committed: bool = False
    commit_sha: str = ""
    pushed: bool = False
    bootstrapped: bool = False
    errors: list[str] = field(default_factory=list)


def bootstrap_worktree(output_dir: Path, remote_url: str) -> tuple[bool, str | None]:
    """Run ``git init -b main`` + ``git remote add origin <url>`` for cold-start.

    Returns ``(ok, error_message)``. Generic git only — the *remote_url*
    was already derived by the backend. Public so a sync engine that
    keeps its own commit step (SharePoint) can reuse the bootstrap.
    """
    try:
        _ = run_git(["init", "-b", "main"], output_dir, timeout=10)
        _ = run_git(["remote", "add", "origin", remote_url], output_dir, timeout=10)
    except GitError as exc:
        return False, f"git init: {exc}"
    log.info("Initialized git repo with origin %s", remote_url)
    return True, None


def _ensure_repo_ready(
    output_dir: Path,
    *,
    push: bool,
    backend: MirrorBackend,
    target: MirrorTarget | None,
    result: CommitAndPushResult,
) -> bool:
    """Bootstrap-or-refuse the workdir; True if we may proceed to commit."""
    if is_git_repo(output_dir):
        return True
    remote_url = backend.resolve_remote(target) if (push and target is not None) else None
    if not (push and remote_url is not None):
        raise MirrorError(
            f"not a git repository: {output_dir}. "
            f"Run `git init {output_dir}` (or clone the mirror) before syncing."
        )
    ok, err = bootstrap_worktree(output_dir, remote_url)
    if not ok:
        assert err is not None  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
        log.error(err)
        result.errors.append(err)
        return False
    result.bootstrapped = True
    return True


def _do_commit(output_dir: Path, commit_message: str, result: CommitAndPushResult) -> None:
    """Stage + commit; thread results into *result* and print status."""
    committed, sha = git_commit(output_dir, commit_message)
    result.committed = committed
    result.commit_sha = sha
    if committed:
        log.info("Committed: %s", sha[:8] if sha else "(unknown)")
    else:
        log.info("Nothing to commit (all changes were already staged).")


def _ensure_remote(
    backend: MirrorBackend, target: MirrorTarget, result: CommitAndPushResult
) -> bool:
    """Verify-or-create the remote; True if we may proceed to push."""
    try:
        outcome = backend.ensure_remote(target)
    except MirrorEnsureError as exc:
        log.error(str(exc))
        result.errors.append(str(exc))
        return False
    if outcome.status == "unreachable":
        log.warning(
            "Skipping remote ensure (%s); push will retry if reachable.",
            outcome.reason,
        )
    elif outcome.status == "created":
        log.info("Created remote: %s", outcome.remote_url or "(unknown)")
    return True


def _do_push(
    output_dir: Path,
    *,
    backend: MirrorBackend,
    target: MirrorTarget | None,
    result: CommitAndPushResult,
) -> None:
    """Optionally ensure-remote, then push; thread errors into *result*."""
    if target is not None and not _ensure_remote(backend, target, result):
        return
    try:
        backend.push(output_dir)
    except MirrorPushError as exc:
        log.error("push: %s", exc)
        result.errors.append(f"push: {exc}")
        return
    log.info("Pushed to remote.")
    result.pushed = True


def commit_and_push(
    output_dir: Path,
    *,
    commit_message: str,
    backend: MirrorBackend,
    target: MirrorTarget | None = None,
    push: bool = False,
) -> CommitAndPushResult:
    """Commit any pending changes under *output_dir* and optionally push.

    Args:
        output_dir: Root of the sync mirror. Must already be a git
            working tree unless ``push`` is True and *target* resolves a
            remote via *backend*, in which case the cold-start bootstrap
            runs first.
        commit_message: Pre-rendered commit message.
        backend: The :class:`~mdd.mirror.protocol.MirrorBackend` that
            resolves the remote, auto-creates it, and performs the push.
        target: The mirror destination. Required when ``push=True`` if
            the mirror isn't already a git work-tree, or if the remote
            project may not exist yet. ``None`` pushes to an existing
            ``origin`` without an ensure step.
        push: If True, push after commit.

    Returns:
        :class:`CommitAndPushResult` describing what happened.

    Raises:
        MirrorError: When *output_dir* is not a git work-tree and
            cold-start bootstrap is unavailable, or when a commit step
            fails for a reason other than "nothing to commit".
    """
    result = CommitAndPushResult()
    if not _ensure_repo_ready(output_dir, push=push, backend=backend, target=target, result=result):
        return result

    _do_commit(output_dir, commit_message, result)

    if not push:
        return result
    if not result.committed and not result.bootstrapped:
        # Nothing to push.
        return result

    _do_push(output_dir, backend=backend, target=target, result=result)
    return result
