"""Generic git mirror backend.

A provider-agnostic backend for a work-tree that already has an
``origin`` remote (a plain ``git clone``). It assumes the remote exists,
imposes no host allow-list, and performs a plain ``git`` push. This is
the default backend for the open-source core: no GitLab, no VPN probe,
no host allow-list and no data-protection gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mdd.mirror.errors import MirrorPushError as MirrorPushError  # re-exported for callers
from mdd.mirror.protocol import EnsureOutcome
from mdd.utils.git import GitError, is_git_repo, run_git

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.mirror.protocol import MirrorTarget


class GenericGitBackend:
    """Push to a pre-configured ``origin`` with no provider-specific policy."""

    def resolve_remote(self, target: MirrorTarget) -> str | None:  # noqa: ARG002
        # The work-tree is expected to already have an ``origin``; there
        # is nothing to derive for the cold-start bootstrap.
        return None

    def ensure_remote(self, target: MirrorTarget) -> EnsureOutcome:  # noqa: ARG002
        # No auto-create: a plain clone's remote is assumed to exist.
        return EnsureOutcome(status="exists")

    def guard_remote(self, path: Path) -> None:  # noqa: ARG002
        # No host allow-list and no data-protection gate in the generic
        # core — the wrapper/backend that knows the deployment adds those.
        return

    def reachable(self) -> bool:
        return True

    def web_url(self, path: Path) -> str | None:  # noqa: ARG002
        """Return ``None``: a plain git remote has no known browse convention.

        Deriving one would mean guessing the host's blob-path shape
        (``/-/blob/`` on GitLab, ``/blob/`` on GitHub, ``/src/branch/`` on
        Gitea) and that the origin is browsable at all — a wrong guess
        publishes a dead link. A backend that knows its forge implements this
        on top of :func:`mdd.mirror.web.git_blob_url` instead.
        """
        return None

    def push(self, path: Path, *, message: str | None = None) -> None:
        """Commit any dirty changes with *message* and ``git push`` the work-tree."""
        self.guard_remote(path)
        if not is_git_repo(path):
            raise MirrorPushError(f"'{path}' is not inside a git work-tree")
        try:
            _commit_if_dirty(path, message)
            _pull_and_push(path)
        except GitError as exc:
            raise MirrorPushError(str(exc)) from exc


def _commit_if_dirty(path: Path, message: str | None) -> None:
    status = run_git(["status", "--porcelain"], path, timeout=10)
    if not status.stdout.strip():
        return
    _ = run_git(["add", "-A"], path)
    _ = run_git(["commit", "-m", message or "chore(mirror): sync"], path, timeout=60)


def _has_upstream(path: Path) -> bool:
    try:
        _ = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], path, timeout=10)
    except GitError:
        return False
    return True


def _pull_and_push(path: Path) -> None:
    if _has_upstream(path):
        _ = run_git(["pull", "--rebase"], path, timeout=60)
        _ = run_git(["push"], path, timeout=60)
        return
    current = _pushable_branch(path)
    # ``--end-of-options`` keeps git from reading the remote or the branch
    # name as an option, whatever the name looks like.
    _ = run_git(["push", "-u", "--end-of-options", "origin", current], path, timeout=60)


def _pushable_branch(path: Path) -> str:
    """Return the checked-out branch name, or refuse one that cannot be pushed by name.

    A detached HEAD has no branch to push. A name starting with ``-`` would
    be read by ``git push`` as an option, and git itself refuses to create a
    branch with such a name — but a ref like ``refs/heads/--mirror`` is still
    valid and can arrive via a clone. A name starting with ``+`` is a valid
    branch name, but ``git push`` reads it as a forced refspec (``+main``
    force-updates ``main``), which ``--end-of-options`` does not prevent. Any
    other name that ``git check-ref-format --branch`` rejects is refused too.
    """
    current = run_git(["rev-parse", "--abbrev-ref", "HEAD"], path).stdout.strip()
    if current == "HEAD":
        raise MirrorPushError(f"cannot push '{path}': HEAD is detached; check out a branch first")
    if current.startswith(("-", "+")) or not _is_valid_branch_name(current, path):
        raise MirrorPushError(
            f"cannot push '{path}': current branch name {current!r} cannot be "
            f"pushed by name; rename the branch first"
        )
    return current


def _is_valid_branch_name(name: str, path: Path) -> bool:
    try:
        _ = run_git(["check-ref-format", "--branch", name], path, timeout=10)
    except GitError:
        return False
    return True
