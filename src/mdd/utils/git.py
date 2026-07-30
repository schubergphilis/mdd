"""Shared git subprocess helpers.

This module holds the one copy of the ``run_git`` / ``is_dirty`` /
``is_git_repo`` helpers that the sync engines and the mirror backends
share. Each consuming module keeps its own boundary exception
(``ApplyError``, ``MirrorPushError``) and wraps :class:`GitError` at the
call site.

Inline ``subprocess.run`` calls that don't fit the ``run_git`` shape
still exist in a few callers; this module's public surface is meant to
stay stable so they can move over.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


__all__ = ["GitError", "is_dirty", "is_git_repo", "run_git", "run_git_lenient"]


class GitError(RuntimeError):
    """Raised when a ``git`` invocation fails.

    Callers at module boundaries (``PushError``, ``ApplyError``) should
    catch this and ``raise ... from exc`` to preserve their public
    exception identity.
    """


def run_git(args: list[str], cwd: Path, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` in *cwd* and return the :class:`CompletedProcess`.

    Args:
        args: Git sub-command and its arguments (no leading ``"git"``).
        cwd: Working directory for the git invocation.
        timeout: Seconds before ``subprocess`` raises ``TimeoutExpired``.

    Raises:
        GitError: On non-zero exit, missing ``git`` binary
            (``FileNotFoundError``) or ``TimeoutExpired``. The original
            exception is chained via ``__cause__``.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]!r} timed out after {timeout}s") from exc

    if result.returncode != 0:
        raise GitError(
            f"git {args[0]!r} failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result


def run_git_lenient(
    args: list[str], cwd: Path, *, timeout: int = 30
) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` and return the :class:`CompletedProcess` without raising on non-zero.

    Caller-friendly variant of :func:`run_git` for cases where the
    distinction between "expected non-zero" (e.g. ``git commit`` with
    "nothing to commit") and "actual error" lives in the stdout/stderr
    text. ``FileNotFoundError`` (missing ``git`` binary) and
    ``TimeoutExpired`` still surface as :class:`GitError` — those aren't
    recoverable from stdout.
    """
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]!r} timed out after {timeout}s") from exc


def is_dirty(path: Path) -> bool:
    """Return True if the git working tree at *path* has uncommitted changes.

    Tolerates a missing ``git`` binary (returns ``False``). Returns
    ``False`` for any non-zero git exit (e.g. not a work-tree) on the
    principle that ``is_dirty`` callers want a yes/no answer; the
    explicit "is this a repo?" question belongs to :func:`is_git_repo`.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return False
    return bool(result.returncode == 0 and result.stdout.strip())


def is_git_repo(path: Path) -> bool:
    """Return True if *path* is inside a git working tree.

    Uses ``git rev-parse --is-inside-work-tree``.
    """
    if not path.exists():
        return False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"
