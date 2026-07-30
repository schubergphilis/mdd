"""Tests for :mod:`mdd.confluence.sync.deletions`.

Covers the branch between git-backed deletion (``git rm``) and plain-filesystem
deletion (``Path.unlink`` / ``shutil.rmtree``). The latter applies when the
sync output directory is not a git working tree, e.g. ``--read-only`` mirrors
or fresh ``--output`` directories.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

from mdd.confluence.sync._types import SyncOptions, SyncSummary
from mdd.confluence.sync.deletions import (
    _delete_path,  # pyright: ignore[reportPrivateUsage]
    apply_deletions,
)
from mdd.confluence.sync_diff import EventKind, SyncEvent

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit so ``git rm`` can succeed."""
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=str(path), check=True, capture_output=True
    )
    # Seed an initial commit so we have HEAD to rm against.
    (path / ".keep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(path), check=True, capture_output=True)


def _make_page_with_attachments(output_dir: Path) -> tuple[Path, Path]:
    """Create ``page.md`` and ``page-attachments/blob.bin`` under *output_dir*."""
    page = output_dir / "page.md"
    page.write_text("---\nconfluence:\n  id: '42'\n---\nbody\n")
    att_dir = output_dir / "page-attachments"
    att_dir.mkdir()
    (att_dir / "blob.bin").write_bytes(b"\x00\x01\x02")
    return page, att_dir


def _stage_existing(output_dir: Path) -> None:
    """Stage and commit the seeded page/attachments in a git repo."""
    subprocess.run(["git", "add", "-A"], cwd=str(output_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"], cwd=str(output_dir), check=True, capture_output=True
    )


def test_delete_path_git_repo_uses_git_rm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """In a git working tree, ``_delete_path`` MUST shell out to ``git rm``
    (existing behaviour) for both the page file and its attachments dir."""
    _init_git_repo(tmp_path)
    page, att_dir = _make_page_with_attachments(tmp_path)
    _stage_existing(tmp_path)

    summary = SyncSummary()
    ok = _delete_path(page, tmp_path, summary, "delete 42")

    assert ok is True
    assert not page.exists(), "page file MUST be removed by git rm"
    assert not att_dir.exists(), "attachment dir MUST be removed by git rm -r"
    assert summary.failures == []
    captured = capsys.readouterr()
    assert "[FAIL]" not in captured.err
    assert "[FAIL]" not in captured.out

    # The removal MUST be staged in git's index too (this is what `git rm` does
    # beyond plain ``Path.unlink``).
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "D  page.md" in status.stdout
    assert "D  page-attachments/blob.bin" in status.stdout


def test_delete_path_non_git_dir_uses_filesystem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """On a non-git output dir, ``_delete_path`` MUST use plain filesystem
    deletion — no ``git rm`` shell-out, no ``[FAIL]`` line."""
    page, att_dir = _make_page_with_attachments(tmp_path)

    summary = SyncSummary()
    with patch("mdd.confluence.sync.deletions.git_rm") as mock_git_rm:
        ok = _delete_path(page, tmp_path, summary, "delete 42")

    assert ok is True
    assert not page.exists(), "page file MUST be removed"
    assert not att_dir.exists(), "attachment dir MUST be removed"
    assert summary.failures == []
    mock_git_rm.assert_not_called()

    captured = capsys.readouterr()
    assert "[FAIL]" not in captured.err
    assert "[FAIL]" not in captured.out


def test_delete_path_non_git_no_attachments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No attachments dir present: page-only deletion still succeeds in non-git mode."""
    page = tmp_path / "page.md"
    page.write_text("---\nconfluence:\n  id: '7'\n---\nbody\n")

    summary = SyncSummary()
    with patch("mdd.confluence.sync.deletions.git_rm") as mock_git_rm:
        ok = _delete_path(page, tmp_path, summary, "delete 7")

    assert ok is True
    assert not page.exists()
    assert summary.failures == []
    mock_git_rm.assert_not_called()
    captured = capsys.readouterr()
    assert "[FAIL]" not in captured.err


def test_delete_path_non_git_missing_page_is_ok(tmp_path: Path) -> None:
    """``Path.unlink(missing_ok=True)`` semantics: deleting an absent file is success."""
    page = tmp_path / "ghost.md"

    summary = SyncSummary()
    ok = _delete_path(page, tmp_path, summary, "delete 99")

    assert ok is True
    assert summary.failures == []


def test_apply_deletions_non_git_dir(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """End-to-end: ``apply_deletions`` on a non-git mirror physically removes files
    without logging any error.

    Regression: every DELETED event used to run ``git rm``, which failed with
    ``fatal: not a git repository`` (exit 128) on a plain mirror.
    """
    page, att_dir = _make_page_with_attachments(tmp_path)
    events = [
        SyncEvent(
            kind=EventKind.DELETED,
            page_id="42",
            current_path=str(page),
        )
    ]
    summary = SyncSummary()
    with caplog.at_level("INFO", logger="mdd.confluence.sync.deletions"):
        apply_deletions(events, tmp_path, SyncOptions(), summary)

    assert summary.deleted == 1
    assert summary.failures == []
    assert not page.exists()
    assert not att_dir.exists()
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert not any(r.levelname == "ERROR" for r in caplog.records)
    assert "delete:" in msgs
